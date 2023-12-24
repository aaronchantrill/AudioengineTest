# -*- coding: utf-8 -*-
import abc
import math
import sys
import unittest
from blessings import Terminal

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

def devices(library):
    if library == 'pyaudio':
        pa = pyaudio.PyAudio()
        input_devs = []
        num_devices = pa.get_device_count()
        print(f"Found {num_devices} pyAudio devices")
        for i in range(num_devices):
            print(f"{i} {pa.get_device_info_by_index(i)['name']}")
    elif library == "alsaaudio":
        devices = set(alsaaudio.pcms(alsaaudio.PCM_CAPTURE))
        device_names = sorted(list(devices))
        num_devices = len(device_names)
        print('Found %d ALSA devices', num_devices)
        for device_name in device_names:
            print(f"{device_name}")


def println(string, displaywidth, scroll=False):
    """
    Print to the screen, overwriting
    """
    # check and see if string ends with a line feed
    # clear the current line
    columns = displaywidth - 1
    sys.stdout.write("{}{}\r".format(
        string, " " * (columns - len(string)))
    )
    if (scroll):
        sys.stdout.write("\n")
    sys.stdout.flush()


def mic_volume(*args, **kwargs):
    try:
        recording = kwargs['recording']
        snr = kwargs['snr']
        minsnr = kwargs['minsnr']
        maxsnr = kwargs['maxsnr']
        mean = kwargs['mean']
        threshold = kwargs['threshold']
    except KeyError:
        return
    try:
        displaywidth = Terminal().width - 6
    except TypeError:
        displaywidth = 20
    snrrange = maxsnr - minsnr
    if snrrange == 0:
        snrrange = 1  # to avoid divide by zero below

    feedback = ["+"] if recording else ["-"]
    feedback.extend(
        list("".join([
            "||",
            ("=" * int(displaywidth * ((snr - minsnr) / snrrange))),
            ("-" * int(displaywidth * ((maxsnr - snr) / snrrange))),
            "||"
        ]))
    )
    # insert markers for mean and threshold
    if (minsnr < mean < maxsnr):
        feedback[int(displaywidth * ((mean - minsnr) / snrrange))] = 'm'
    if (minsnr < threshold < maxsnr):
        feedback[int(displaywidth * ((threshold - minsnr) / snrrange))] = 't'
    println("".join(feedback), displaywidth)


class AudioProcessor:
    def __init__(self, *args, **kwargs):
        self.input_device = kwargs['input_device']
        self.sample_format = kwargs['sample_format']
        self.channels = kwargs['channels']
        self.sample_rate = kwargs['sample_rate']
        self.periodsize = kwargs['periodsize']
        self.sample_bits = kwargs['sample_bits']
        self.VAD = SNRVAD()


    @abc.abstractmethod
    def run(self):
        pass


class PyAudioProcessor(AudioProcessor):
    def __init__(
        self,
        input_device=9,
        channels=1,
        sample_rate=16000,
        sample_format=pyaudio.paInt16,
        sample_bits=16,
        periodsize=480
    ):
        super().__init__(
            input_device=input_device,
            channels=channels,
            sample_rate=sample_rate,
            sample_format=sample_format,
            sample_bits=sample_bits,
            periodsize=periodsize
        )
        self.input_device = int(self.input_device)
        self.stream = pyaudio.PyAudio().open(
            format=self.sample_format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.input_device,
            frames_per_buffer=self.periodsize
        )

    def run(self):
        try:
            recording = False
            while True:
                input_data = self.stream.read(self.periodsize)
                recording = self.VAD._voice_detected(
                    input_data,
                    input_bits=self.sample_bits,
                    recording=recording
                )
        except KeyboardInterrupt:
            pass
        finally:
            # Close the stream
            self.stream.close()


class AlsaAudioProcessor(AudioProcessor):
    def __init__(
        self,
        input_device='default',
        channels=1,
        sample_rate=16000,
        sample_format=alsaaudio.PCM_FORMAT_S16_LE,
        sample_bits=16,
        periodsize=480
    ):
        super().__init__(
            input_device=input_device,
            channels=channels,
            sample_rate=sample_rate,
            sample_format=sample_format,
            sample_bits=sample_bits,
            periodsize=periodsize
        )
        self.stream = alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            self.input_device,
            channels=self.channels,
            rate=self.sample_rate,
            format=self.sample_format,
            periodsize=self.periodsize
        )

    def run(self):
        try:
            recording = False
            while True:
                input_data = self.stream.read()[1]
                recording = self.VAD._voice_detected(
                    input_data,
                    input_bits=self.sample_bits,
                    recording=recording
                )
        except KeyboardInterrupt:
            pass
        finally:
            # Close the stream
            self.stream.close()


# This is a really simple voice activity detector
# based on what Naomi currently uses. When you create it,
# you can pass in a decibel level which defaults to 30dB.
# The optimal value for decibel level appears to be
# affected not only by noise levels where you are, but
# also the specific sound card or even microphone you
# are using.
# Once the audio level goes above this level, recording
# starts. Once the level goes below this for timeout
# seconds (floating point, can be fractional), then
# recording stops. If the total length of the recording is
# over twice the length of timeout, then the recorded audio
# is returned for processing.
class SNRVAD():
    _maxsnr = None
    _minsnr = None
    _visualizations = []

    def __init__(self, *args, **kwargs):
        timeout = 1
        minimum_capture = 0.5
        threshold = 30
        # if the audio decibel is greater than threshold, then consider this
        # having detected a voice.
        self._threshold = threshold
        # Keep track of the number of audio levels
        self.distribution = {}

    def _voice_detected(self, *args, **kwargs):
        frame = args[0]
        recording = False
        if "recording" in kwargs:
            recording = kwargs["recording"]
        rms = audioop.rms(frame, int(kwargs['input_bits'] / 8))
        if rms > 0 and self._threshold > 0:
            snr = round(20.0 * math.log(rms / self._threshold, 10))
        else:
            snr = 0
        if snr in self.distribution:
            self.distribution[snr] += 1
        else:
            self.distribution[snr] = 1
        # calculate the mean and standard deviation
        sum1 = sum([
            value * (key ** 2) for key, value in self.distribution.items()
        ])
        items = sum([value for value in self.distribution.values()])
        if items > 1:
            # mean = sum( value * freq )/items
            mean = sum(
                [key * value for key, value in self.distribution.items()]
            ) / items
            stddev = math.sqrt((sum1 - (items * (mean ** 2))) / (items - 1))
            self._threshold = mean + stddev
            # We'll say that the max possible value for SNR is mean+3*stddev
            if self._minsnr is None:
                self._minsnr = snr
            if self._maxsnr is None:
                self._maxsnr = snr
            maxsnr = mean + 3 * stddev
            if snr > maxsnr:
                maxsnr = snr
            if maxsnr > self._maxsnr:
                self._maxsnr = maxsnr
            minsnr = mean - 3 * stddev
            if snr < minsnr:
                minsnr = snr
            if minsnr < self._minsnr:
                self._minsnr = minsnr
            # Loop through visualization plugins
            mic_volume(
                recording=recording,
                snr=snr,
                minsnr=self._minsnr,
                maxsnr=self._maxsnr,
                mean=mean,
                threshold=self._threshold
            )
        if(items > 100):
            # Every 50 samples (about 1-3 seconds), rescale,
            # allowing changes in the environment to be
            # recognized more quickly.
            self.distribution = {
                key: (
                    (value + 1) / 2
                ) for key, value in self.distribution.items() if value > 1
            }
        threshold = self._threshold
        # If we are already recording, reduce the threshold so as
        # the user's voice trails off, we continue to record.
        # Here I am setting it to the halfway point between threshold
        # and mean.
        if(recording):
            threshold = (mean + threshold) / 2
        if(snr < threshold):
            response = False
        else:
            response = True
        return response


def main():
    if pyaudio is None and alsaaudio is None:
        print("Error: Both pyaudio and pyalsaaudio libraries are not installed.")
        sys.exit(1)

    available_libraries = []
    if pyaudio:
        available_libraries.append('pyaudio')
    if alsaaudio:
        available_libraries.append('alsaaudio')

    print("Available audio libraries:", available_libraries)

    library_choice = input("Choose an audio library ({}): ".format("/".join(available_libraries)))

    if library_choice not in available_libraries:
        print("Invalid choice. Exiting.")
        sys.exit(1)

    devices(library_choice)

    input_device = input("Enter input device index or 'default': ")

    print("Streaming... Press Ctrl+C to stop.")

    audio_processor = None
    if(library_choice == 'pyaudio'):
        audio_processor = PyAudioProcessor(input_device=input_device)
    elif(library_choice == 'alsaaudio'):
        audio_processor = AlsaAudioProcessor(input_device=input_device)
    if(audio_processor):
        audio_processor.run()

if __name__ == "__main__":
    main()
