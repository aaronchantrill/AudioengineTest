import argparse
import sys
from core.assistant import Assistant
from core import pluginstore
from core import profile
from pprint import pprint
# 'audioop' is deprecated and slated for removal in Python 3.13
try:
    import audioop
except ImportError:
    from pydub import pyaudioop as audioop

try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    import alsaaudio
except ImportError:
    alsaaudio = None


def main(args=None):
    # Load plugins
    profile.set_arg('plugins', pluginstore.PluginStore())
    profile.get_arg('plugins').detect_plugins()
    # Get defaults from profile
    parser = argparse.ArgumentParser(
        prog="AudioengineTest",
        description='Testing a new audio system for Naomi'
    )
    parser.add_argument(
        '--audio-engine',
        choices=['pyaudio','pyalsaaudio'],
        dest='audio_engine',
        help='Choose an audio engine (pyaudio or pyalsaaudio)',
        nargs=1
    )
    parser.add_argument(
        '--input-device',
        dest='input_device',
        help='Choose an audio device',
        nargs=1
    )
    parser.add_argument(
        '--vad',
        dest='vad',
        help='Choose a voice activity detector',
        nargs=1
    )
    p_args = parser.parse_args(args)

    # # Get the plugins
    # profile.set_arg('plugins', pluginstore.PluginStore())
    # profile.get_arg('plugins').detect_plugins()
    #
    # # Load the audioengine
    # available_audioengines = [info.name for info in profile.get_arg('plugins').get_plugins_by_category('audioengine')]
    #
    # if p_args.audio_engine in available_audioengines:
    #     library_choice = p_args.audio_engine
    # else:
    #     if(len(available_audioengines)>1):
    #         library_choice = input("Choose an audio library ({}): ".format("/".join(available_audioengines)))
    #     elif(len(available_audioengines)>0):
    #         library_choice = available_audioengines[0]
    #     else:
    #         print("Error: no audio engine available", file=sys.stderr)
    #         sys.exit(1)
    #
    # ae_info = profile.get_arg('plugins').get_plugin(
    #     library_choice,
    #     category='audioengine'
    # )
    #
    # audio = ae_info.plugin_class(ae_info)
    #
    # # Get the audioengine devices
    # input_devices = [
    #     device.slug for device in audio.get_devices(
    #         device_type=audioengine.DEVICE_TYPE_INPUT
    #     )
    # ]
    #
    # if p_args.input_device in input_devices:
    #     input_device = p_args.input_device
    # else:
    #     if(len(input_devices)>1):
    #         input_device = input("Choose an input device ({}): ".format(", ".join(input_devices)))
    #     elif(len(input_devices)>0):
    #         input_device = input_devices[0]
    #     else:
    #         print("Error: no input device available", file=sys.stderr)
    #         sys.exit(1)
    #
    # available_vads = [info.name for info in profile.get_arg('plugins').get_plugins_by_category('vad')]
    # if p_args.vad in available_vads:
    #     vad_slug = p_args.vad
    # else:
    #     if(len(available_vads)>1):
    #         vad_slug = input("Choose a VAD ({}): ".format(", ".join(available_vads)))
    #     elif(len(available_vads)>0):
    #         vad_slug = p_args.vad
    #     else:
    #         print("Error: no vad available", file=sys.stderr)
    #         sys.exit(1)

    # Load the library
    print('enter main loop')
    assistant = Assistant(p_args)
    assistant.run()
