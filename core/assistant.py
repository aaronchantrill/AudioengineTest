import collections
import contextlib
import logging
import os
import tempfile
import threading
import wave
from core import audioengine
from core import commandline as interface
from core import i18n
from core import mic
from core import paths
from core import profile
from core import visualizations
from datetime import datetime
import pdb

_ = None


class Assistant:
    def __init__(self, *args, **kwargs):
        global _
        self._logger = logging.getLogger(__name__)
        translations = i18n.parse_translations(paths.data('locale'))
        translator = i18n.GettextMixin(translations)
        self.gettext = translator.gettext
        _ = self.gettext
        self._interface = interface.commandline()
        keyword = profile.get_profile_var(['keyword'], ['Assistant'])
        p_args = args[0]
        visualizations.load_visualizations(self)
        self.recordings_queue = collections.deque([], maxlen=10)
        if hasattr(self, "settings"):
            # set a variable here to tell us if all settings are
            # completed or not
            # If all settings do not currently exist, go ahead and
            # re-query all settings for this plugin
            settings_complete = True
            # Step through the settings and check for
            # any missing settings
            for setting in self.settings():
                if not profile.check_profile_var_exists(setting):
                    self._logger.info(
                        "{} setting does not exist".format(setting)
                    )
                    # Go ahead and pull the setting
                    settings_complete = False
            visualizations.run_visualization(
                "output",
                self._interface.status_text(_(
                    "Configuring {}"
                ).format(
                    keyword
                )),
                timestamp=False
            )
            for setting in self.settings():
                self._interface.get_setting(
                    setting, self.settings()[setting]
                )
            # Save the profile with the new settings
            profile.save_profile()

    def settings(self):
        _ = self.gettext
        return collections.OrderedDict(
            [
                (
                    ("keyword",), {
                        "title": _("By what name would you like to call me?"),
                        "description": _("A good choice for a name would have multiple syllables and not sound like any common words."),
                        "default": "Computer",
                        "return_list": True
                    }
                ),
                (
                    ("audio_engine",), {
                        "type": "listbox",
                        "title": _("Please select an audio engine"),
                        "options": self.get_audio_engines,
                        "default": "pyaudio"
                    }
                ),
                (
                    ("audio", "input_device"), {
                        "type": "listbox",
                        "title": _("Please select an input device"),
                        "options": self.get_input_devices,
                        "default": lambda: "pulse" if ("pulse" in self.get_input_devices())else self.get_default_input_audio_device()
                    }
                ),
                (
                    ("vad_engine"), {
                        "type": "listbox",
                        "title": _("Please select a voice activity detector engine"),
                        "description": _("The voice activity detector detects speech near me and lets me know when to start paying attention"),
                        "options": [info.name for info in profile.get_arg('plugins').get_plugins_by_category("vad")],
                        "default": "snr_vad"
                    }
                ),
                (
                    ("audio", "input_rate"), {
                        "type": "number",
                        "title": _("Input device rate (in Hertz)"),
                        "description": _("The input audio rate in Hz. Most speech to text engines expect audio to be 16000Hz, so it is usually best to leave this value at the default"),
                        "default": 16000
                    }
                ),
                (
                    ("audio", "input_chunksize"), {
                        "type": "number",
                        "title": _("Input device chunk size"),
                        "description": _("The size (in bytes) of each input chunk"),
                        "default": int(int(profile.get(['audio', 'input_rate'], 16000)) * 0.03) if (profile.get(['vad_engine'], 'snr_vad') == 'webrtc_vad') else 1024
                    }
                ),
                (
                    ("passive_stt", "engine"), {
                        "type": "listbox",
                        "title": _("Please select a passive speech to text engine"),
                        "description": _("The passive STT engine processes everything you say near me. It is highly recommended to use an offline engine like sphinx."),
                        "options": [info.name for info in profile.get_arg('plugins').get_plugins_by_category("stt")],
                        "default": "sphinx"
                    }
                ),
                (
                    ("active_stt", "engine"), {
                        "type": "listbox",
                        "title": _("Please select an active speech to text engine"),
                        "description": _("After I hear my wake word, this engine processes everything you say. I recommend an offline option, but you could also use an online option like Google Voice."),
                        "options": [info.name for info in profile.get_arg('plugins').get_plugins_by_category("stt")],
                        "default": "sphinx"
                    }
                )
            ]
        )

    # Return a list of currently installed audio engines.
    @staticmethod
    def get_audio_engines():
        audioengines = [
            ae_info.name
            for ae_info
            in profile.get_arg('plugins').get_plugins_by_category(
                category='audioengine'
            )
        ]
        return audioengines

    @staticmethod
    def get_audio_devices(device_type):
        ae_info = profile.get_arg('plugins').get_plugin(
            profile.get_profile_var(['audio_engine']),
            category='audioengine'
        )
        # AaronC 2018-09-14 Get a list of available output devices
        audio_engine = ae_info.plugin_class(ae_info, profile.get_profile())
        # AaronC 2018-09-14 Get a list of available input devices
        input_devices = [device.slug for device in audio_engine.get_devices(
            device_type=device_type
        )]
        return input_devices

    def get_output_devices(self):
        return self.get_audio_devices(audioengine.DEVICE_TYPE_OUTPUT)

    def get_input_devices(self):
        return self.get_audio_devices(audioengine.DEVICE_TYPE_INPUT)

    def get_default_output_audio_device(self):
        return self.get_default_audio_device(audioengine.DEVICE_TYPE_OUTPUT).slug

    def get_default_input_audio_device(self):
        return self.get_default_audio_device(audioengine.DEVICE_TYPE_INPUT).slug

    @staticmethod
    def get_default_audio_device(device_type):
        ae_info = profile.get_arg('plugins').get_plugin(
            profile.get_profile_var(['audio_engine']),
            category='audioengine'
        )
        audio_engine = ae_info.plugin_class(ae_info, profile.get_profile())
        return audio_engine.get_default_device(device_type)

    def list_audio_devices(self):
        for device in self.audio.get_devices():
            device.print_device_info(
                verbose=(self._logger.getEffectiveLevel() == logging.DEBUG))

    def run(self):
        ae_info = profile.get_arg('plugins').get_plugin(
            profile.get_profile_var(['audio_engine']),
            category='audioengine'
        )
        # AaronC 2018-09-14 Get a list of available output devices
        audio_engine = ae_info.plugin_class(ae_info, profile.get_profile())
        # AaronC 2018-09-14 Get the input device
        input_device_slug = profile.get_profile_var(["audio", "input_device"])
        if not input_device_slug:
            input_device_slug = audio_engine.get_default_device(output=False).slug
        # try recording a sample
        self.input_device = audio_engine.get_device_by_slug(
            profile.get_profile_var(['audio', 'input_device'])
        )
        vad_slug = profile.get_profile_var(['vad_engine'], 'snr_vad')
        vad_info = profile.get_arg('plugins').get_plugin(
            vad_slug,
            category='vad'
        )
        vad_plugin = vad_info.plugin_class(self.input_device)
        # STT Engine
        stt_thread = None
        active_stt_slug = profile.get_profile_var(
            ['active_stt', 'engine']
        )
        if (not active_stt_slug):
            active_stt_slug = 'sphinx'
            self._logger.warning(
                " ".join([
                    "stt_engine not specified in profile,",
                    "using default ({}).".format(active_stt_slug)
                ])
            )
        self._logger.info(
            "Using STT (speech to text) engine '{}'".format(active_stt_slug)
        )
        active_stt_plugin_info = profile.get_arg('plugins').get_plugin(
            active_stt_slug,
            category='stt'
        )
        #active_phrases = self.brain.get_plugin_phrases(passive_listen or verify_wakeword)
        self.active_stt_plugin = active_stt_plugin_info.plugin_class(
            'default',
            [],
            active_stt_plugin_info
        )
        self.mic = mic.Mic(
            input_device=self.input_device,
            active_stt_plugin=self.active_stt_plugin
        )
        try:
            while self.mic.Continue:
                # put the audio in a queue and call the stt engine
                self.mic.add_to_queue(vad_plugin.get_audio())
                if not (stt_thread and hasattr(stt_thread, "is_alive") and stt_thread.is_alive()):
                    # start the thread
                    stt_thread = threading.Thread(
                        target=self.mic.listen
                    )
                    stt_thread.start()
        except KeyboardInterrupt:
            self.mic.Continue = False
        visualizations.run_visualization(
            "output",
            "Exiting..."
        )
