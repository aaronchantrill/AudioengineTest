# -*- coding: utf-8 -*-
import json
import os.path
import sys
from collections import OrderedDict
from core import app_utils
from core import paths
from core import plugin
from core import profile
from core.run_command import run_command
from core.run_command import process_completedprocess
from vosk import Model, KaldiRecognizer
from . import voskvocab


def get_languagemodel_path(path):
    """
    Returns:
        The path of the the pocketsphinx languagemodel file as string
    """
    return os.path.join(path, 'languagemodel')


# This is only required because file.writelines() does not automatically add
# newlines to the lines passed in
def line_generator(items):
    for item in items:
        yield item
        yield "\n"


class VoskSTTPlugin(plugin.STTPlugin):
    """
    The default Speech-to-Text implementation which relies on PocketSphinx.
    """
    _logfile = None

    def __init__(self, *args, **kwargs):
        """
        Initiates Vosk

        Arguments:
        """
        plugin.STTPlugin.__init__(self, *args, **kwargs)
        vosk_model = profile.get(
            ['VOSK STT', 'model'],
            os.path.join(
                paths.sub('vosk'),
                'vosk-model-small-en-us-0.15'
            )
        )
        model = Model(vosk_model, lang="en-us")
        self.rec = KaldiRecognizer(model, 16000)
        scorer_file = os.path.join(
            self.compile_vocabulary(
                self.generate_scorer
            ), "scorer"
        )
        print(f'Vosk scorer file: {scorer_file}')


    def settings(self):
        default_model='vosk-model-small-en-us-0.15'
        vosk_model = profile.get(
            ['VOSK STT', 'model'],
            os.path.join(
                paths.sub('vosk'),
                default_model
            )
        )
        default_model=os.path.basename(vosk_model)
        if not os.path.isdir(os.path.dirname(vosk_model)):
            os.makedirs(os.path.dirname(vosk_model), exist_ok=True)
        if not os.path.isdir(vosk_model):
            # since the model does not exist, download the default to the
            # standard path and unzip it
            source = f"https://alphacephei.com/vosk/models/{default_model}.zip"
            dest = f"{vosk_model}.zip"
            app_utils.download_file(
                source,
                dest
            )
            cmd = [
                'unzip',
                dest,
                '-d', os.path.dirname(vosk_model)
            ]
            completedprocess = run_command(cmd)
        return OrderedDict(
            [
                (
                    ('VOSK STT', 'model'), {
                        'title': self.gettext('VOSK model file'),
                        'description': "".join([
                            self.gettext('This is the VOSK model, downloaded from https://alphacephei.com/vosk/models')
                        ]),
                        'default': vosk_model
                    }
                ),
            ]
        )

    def generate_scorer(self, directory, phrases):
        languagemodel_path = get_languagemodel_path(directory)
        with open(languagemodel_path, "w") as f:
            f.writelines(line_generator(phrases))
        # Generate a list of unique words in phrases,
        # then use that list to generate a dictionary
        # with phonetisaurus
        
        
        return os.path.join(directory, 'scorer')

    def transcribe(self, fp):
        """
        Performs STT, transcribing an audio file and returning the result.

        Arguments:
            fp -- a file object containing audio data
        """
        fp.seek(44)
        data = fp.read()

        if(len(data) == 0):
            self._logger.warn(f"Audio file is empty")
            return ""
        self.rec.AcceptWaveform(data)
        res = json.loads(self.rec.Result())
        result = res['text']
        transcribed = [result] if result != '' else []
        return transcribed
