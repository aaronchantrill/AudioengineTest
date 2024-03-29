# -*- coding: utf-8 -*-
import email
import functools
import imaplib
import logging
import os
import pathlib
import re
import requests
import shutil
import smtplib
from dateutil import parser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from core import i18n
from core import paths
from core import profile
from pytz import timezone
from tqdm.auto import tqdm
from urllib import request as urllib_request


_ = i18n.GettextMixin(i18n.parse_translations(paths.data('locale'))).gettext


# AaronC - This is currently used to clean phone numbers
def clean_number(s):
    return re.sub(r'[^0-9]', '', s)


def get_date(email):
    return parser.parse(email.get('date'))


# The following two functions just check to make sure Naomi has
# access to an imap server for receiving emails/text messages
# and an smtp server for sending emails/texts
def check_imap_config():
    success = True
    USERNAME = profile.get_profile_password(['email', 'username'])
    if(not USERNAME):
        logging.info('Email username not set')
        success = False
    PASSWORD = profile.get_profile_password(['email', 'password'])
    if(not PASSWORD):
        logging.info('Email password not set')
        success = False
    SERVER = profile.get(['email', 'imap', 'server'])
    if(not SERVER):
        logging.info('Email imap server not set')
        success = False
    PORT = profile.get(['email', 'imap', 'port'], 993)
    if(success):
        try:
            conn = imaplib.IMAP4_SSL(SERVER, PORT)
            conn.login(USERNAME, PASSWORD)
            conn.logout()
        except TimeoutError:
            logging.info('IMAP connection timed out (check server name)')
            success = False
        except OSError as e:
            logging.info('IMAP connection error: {}'.format(e))
            success = False
        except imaplib.IMAP4.error as e:
            if hasattr(e, 'args'):
                logging.info(e.args[0])
            success = False
    return success


def check_smtp_config():
    success = True
    USERNAME = profile.get_profile_password(['email', 'username'])
    if(not USERNAME):
        logging.info('Email username not set')
        success = False
    PASSWORD = profile.get_profile_password(['email', 'password'])
    if(not PASSWORD):
        logging.info('Email password not set')
        success = False
    SERVER = profile.get(['email', 'smtp', 'server'])
    if(not SERVER):
        logging.info('Email smtp server not set')
        success = False
    PORT = profile.get(['email', 'smtp', 'port'], 587)
    if(success):
        try:
            session = smtplib.SMTP(
                SERVER,
                PORT,
                profile.get(
                    ['email', 'smtp', 'timeout'],
                    10
                )
            )
            session.starttls()
            session.login(USERNAME, PASSWORD)
            session.quit()
        except TimeoutError:
            logging.info('SMTP connection timed out (check server name)')
            success = False
        except OSError as e:
            logging.info('SMTP connection error: {}'.format(e))
            success = False
        except imaplib.IMAP4.error as e:
            if hasattr(e, 'args'):
                logging.info(e.args[0])
            success = False
    return success


def send_email(
    SUBJECT,
    BODY,
    TO
):
    """Sends an HTML email."""

    USERNAME = profile.get_profile_password(['email', 'username'])
    SENDER = profile.get(['keyword'], ['Naomi'])[0]
    FROM = profile.get_profile_password(['email', 'address'])
    PASSWORD = profile.get_profile_password(['email', 'password'])
    SERVER = profile.get(['email', 'smtp', 'server'])
    PORT = profile.get(['email', 'smtp', 'port'], 587)

    msg = MIMEMultipart()
    msg['From'] = "{} <{}>".format(SENDER, FROM)
    msg['To'] = TO
    msg['Subject'] = SUBJECT
    msg.attach(MIMEText(BODY.encode('UTF-8'), 'html', 'UTF-8'))

    logging.info('using %s, and %s as port', SERVER, PORT)

    session = smtplib.SMTP(SERVER, PORT)

    session.starttls()

    session.login(USERNAME, PASSWORD)
    session.sendmail(msg['From'], msg['To'], msg.as_string())
    session.quit()
    logging.info('Successful.')


def email_user(SUBJECT="", BODY=""):
    """
    sends an email to the user.

    Arguments:
        SUBJECT -- subject line of the email
        BODY -- body text of the email
    """
    SENDER = profile.get(['keyword'], ['Naomi'])[0]
    if not BODY:
        return False

    body = 'Hello {},'.format(profile.get(['first_name']))
    body += '\n\n' + BODY.strip() + '\n\n'
    body += 'Best Regards,\n{}\n'.format(SENDER)

    recipient = None

    if profile.get(['email', 'address']):
        recipient = profile.get_profile_password(['email', 'address'])
        first_name = profile.get(['first_name'])
        last_name = profile.get(['last_name'])
        if first_name and last_name:
            recipient = "{first_name} {last_name} <{recipient}>".format(
                first_name=first_name,
                last_name=last_name,
                recipient=recipient
            )
    else:
        phone_number = clean_number(
            profile.get_profile_password(['phone_number'])
        )
        carrier = profile.get(['carrier'])
        if phone_number and carrier:
            recipient = "{}@{}".format(
                str(phone_number),
                carrier
            )

    if not recipient:
        return False

    try:
        send_email(
            SUBJECT,
            body,
            recipient
        )

    except Exception as e:
        print(e)
        return False
    else:
        return True


def fetch_emails(since=None, email_filter="", markRead=False, limit=None):
    """
        Fetches a list of unread email objects from a user's Email inbox.

        Arguments:
        since -- if provided, no emails before this date will be returned
        markRead -- if True, marks all returned emails as read in target
                    inbox

        Returns:
        A list of unread email objects.
    """
    host = profile.get_profile_var(['email', 'imap', 'server'])
    port = int(profile.get_profile_var(['email', 'imap', 'port'], "993"))
    msgs = []

    conn = imaplib.IMAP4_SSL(host, port)
    conn.debug = 0

    conn.login(
        profile.get_profile_password(['email', 'username']),
        profile.get_profile_password(['email', 'password'])
    )
    conn.select(readonly=(not markRead))

    (retcode, messages) = conn.search(None, email_filter)
    if retcode == 'OK' and messages != [b'']:
        numUnread = len(messages[0].split(b' '))
        if limit and numUnread > limit:
            return numUnread

        for num in messages[0].split(b' '):
            # parse email RFC822 format
            logging.info("num = {}".format(num))
            (retcode, data) = conn.fetch(num, '(RFC822)')
            raw_email = data[0][1]
            raw_email_str = raw_email.decode("utf-8")
            msg = email.message_from_string(raw_email_str)
            if not since or get_date(msg) > since:
                msgs.append(msg)
    conn.close()
    conn.logout()
    return msgs


def get_sender(msg):
    """
        Returns the best-guess sender of an email.

        Arguments:
        email -- the email whose sender is desired

        Returns:
        Sender of the email.
    """
    sender = msg['From']
    m = re.match(r'(.*)\s<.*>', sender)
    if m:
        return m.group(1)
    return sender


def get_sender_email(msg):
    """
        Returns the best-guess email address of the sender.

        Arguments:
        email -- the email whose sender is desired

        Returns:
        Sender of the email.
    """
    sender = msg['From']
    m = re.match(r'.*\s<(.*)>', sender)
    if m:
        return m.group(1)
    return sender


def get_message_text(msg):
    body = ""
    if(msg.is_multipart()):
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get('Content-Disposition'))
            if((ctype == "text/plain") and ('attachment' not in cdispo)):
                body = re.sub('[\\r\\n\\t]+', ' ', part.get_payload())
                break
    else:
        body = re.sub('[\\r\\n\\t]+', ' ', msg.get_payload())
    return body


def mark_read(msg):
    host = profile.get_profile_var(['email', 'imap', 'server'])
    port = int(profile.get_profile_var(['email', 'imap', 'port'], "993"))
    conn = imaplib.IMAP4_SSL(host, port)
    conn.debug = 0

    conn.login(
        profile.get_profile_password(['email', 'username']),
        profile.get_profile_password(['email', 'password'])
    )
    conn.select(readonly=False)
    (retcode, messages) = conn.search(
        None,
        "(HEADER Message-ID {})".format(msg['Message-ID'])
    )
    if(retcode == 'OK' and len(messages)):
        conn.store(messages[0].split()[0], '+FLAGS', '\Seen')
    conn.close()
    conn.logout()


def get_most_recent_date(emails):
    """
        Returns the most recent date of any email in the list provided.

        Arguments:
        emails -- a list of emails to check

        Returns:
        Date of the most recent email.
    """
    dates = [get_date(e) for e in emails]
    dates.sort(reverse=True)
    if dates:
        return dates[0]
    return None


def get_timezone():
    """
    Returns the pytz timezone for a given profile.

    Arguments: None
    """
    return timezone(profile.get(['timezone']))


def generate_tiny_URL(URL):
    """
    Generates a compressed URL.

    Arguments:
        URL -- the original URL to-be compressed
    """
    target = "http://tinyurl.com/api-create.php?url=" + URL
    response = urllib_request.urlopen(target)  # nosec
    return response.read()


def is_negative(phrase):
    """
    Returns True if the input phrase has a negative sentiment.

    Arguments:
        phrase -- the input phrase to-be evaluated
    """
    if(isinstance(phrase, bool)):
        return not phrase
    return bool(
        re.search(
            _('\b(no(t)?|don\'t|stop|end|n|false)\b'),
            phrase,
            re.IGNORECASE
        )
    )


def is_positive(phrase):
    """
        Returns True if the input phrase has a positive sentiment.

        Arguments:
        phrase -- the input phrase to-be evaluated
    """
    if(isinstance(phrase, bool)):
        return phrase
    return bool(
        re.search(
            _('\b(sure|yes|yeah|go|yup|y|true)\b'),
            phrase,
            re.IGNORECASE
        )
    )


# Copied from https://stackoverflow.com/questions/16694907/download-large-file-in-python-with-requests/16696317#16696317
def download_file(url, local_filename=None):
    if(local_filename is None):
        local_filename = url.split('/')[-1]
    path = pathlib.Path(local_filename).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    # NOTE the stream=True parameter below
    r = requests.get(url, stream=True, allow_redirects=True)
    remote_file_size = int(r.headers.get('Content-Length', 0))
    r.close()
    desc = "(Unknown total file size)" if remote_file_size == 0 else ""
    print(f"Downloading from {url}")
    if os.path.isfile(local_filename):
        # check if the size is correct
        local_file_size = os.path.getsize(local_filename)
        if local_file_size < remote_file_size:
            # try to resume download
            resume_header = {'Range': f'bytes={local_file_size}-{remote_file_size}'}
            r = requests.get(
                url,
                headers=resume_header,
                stream=True,
                allow_redirects=True
            )
            if r.status_code != 206:  # Partial Content
                r.raise_for_status()
                raise RuntimeError(f"Request to {url} returned status code {r.status_code}")
            r.raw.read = functools.partial(r.raw.read, decode_content=True)
            with tqdm.wrapattr(
                r.raw,
                "read",
                total=remote_file_size,
                initial=local_file_size,
                desc=desc
            ) as r_raw:
                with path.open("ab") as f:
                    shutil.copyfileobj(r_raw, f)
    else:
        r = requests.get(
            url,
            stream=True,
            allow_redirects=True
        )
        if r.status_code != 200:  # Okay
            r.raise_for_status()
            raise RuntimeError(f"Request to {url} returned status code {r.status_code}")
        r.raw.read = functools.partial(r.raw.read, decode_content=True)
        with tqdm.wrapattr(
            r.raw,
            "read",
            total=remote_file_size,
            desc=desc
        ) as r_raw:
            with path.open("wb") as f:
                shutil.copyfileobj(r_raw, f)
