#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import abc
import collections
import contextlib
import itertools
import json
import math
import os
import sys
import tempfile
import threading
import unittest
import wave
from blessings import Terminal
from datetime import datetime
from vosk import Model, KaldiRecognizer

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


VOSK_MODEL = os.path.expanduser("~/VOSK/vosk-model-en-us-0.22-lgraph")


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


# https://stackoverflow.com/questions/10003143/how-to-slice-a-deque
class sliceable_deque(collections.deque):
    def __getitem__(self, index):
        try:
            return collections.deque.__getitem__(self, index)
        except TypeError:
            return type(self)(
                itertools.islice(
                    self,
                    index.start,
                    index.stop,
                    index.step
                )
            )


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

    def open_stream(self, *args, **kwargs):
        self.stream = pyaudio.PyAudio().open(
            format=self.sample_format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.input_device,
            frames_per_buffer=self.periodsize
        )

    def record(self, *args, **kwargs):
        return self.stream.read(self.periodsize)

    def close_stream(self, *args, **kwargs):
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

    def open_stream(self, *args, **kwargs):
        self.stream = alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            self.input_device,
            channels=self.channels,
            rate=self.sample_rate,
            format=self.sample_format,
            periodsize=self.periodsize
        )

    def record(self, *args, **kwargs):
        return self.stream.read()[1]

    def close_stream(self, *args, **kwargs):
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
class SNRVAD:
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


class Main:
    def __init__(self):
        self.recordings_queue = collections.deque([], maxlen=10)
        self.model = Model(VOSK_MODEL, 16000)
        self.rec = KaldiRecognizer(self.model, 16000)
        self.input_channels = 1
        self.input_bits = 16
        self.input_samplerate = 16000
        try:
            self.displaywidth = Terminal().width
        except TypeError:
            self.displaywidth = 20

    @contextlib.contextmanager
    def _write_frames_to_file(self, frames):
        with tempfile.NamedTemporaryFile(
            mode='w+b',
            suffix=".wav",
            prefix=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        ) as f:
            wav_fp = wave.open(f, 'wb')
            wav_fp.setnchannels(self.input_channels)
            wav_fp.setsampwidth(int(self.input_bits // 8))
            wav_fp.setframerate(self.input_samplerate)
            fragment = b''.join(frames)
            wav_fp.writeframes(fragment)
            wav_fp.close()
            f.seek(0)
            yield f

    def stt(self):
        while True:
            try:
                audio = self.recordings_queue.pop()
                # println(f"Popped {len(audio)} frames from queue", scroll=True)
                # println(f"type: {type(audio)}", scroll=True)
                with self._write_frames_to_file(audio) as f:
                    f.seek(44)
                    data = f.read()
                self.rec.AcceptWaveform(data)
                res = json.loads(self.rec.FinalResult())
                transcription = res['text'].strip()
                if len(transcription) > 0:
                    println(f"<< {transcription} {len(self.recordings_queue)}", self.displaywidth, scroll=True)
                if any(map(lambda v: v in transcription, ["shut down", "shutdown", "turn off", "quit"])):
                    self.say("okay, quitting")
                    self.Continue = False
                if transcription.startswith("say "):
                    # start a speak thread
                    self.say("here is what you said to say")
                    self.say(transcription[4:])
            except IndexError:
                break

    def main(self):
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
            audio_processor = PyAudioProcessor(
                input_device=input_device,
                channels=self.input_channels,
                sample_bits=self.input_bits,
                sample_rate=self.input_samplerate
            )
        elif(library_choice == 'alsaaudio'):
            audio_processor = AlsaAudioProcessor(
                input_device=input_device,
                channels=self.input_channels,
                sample_bits=self.input_bits,
                sample_rate=self.input_samplerate
            )

        VAD = SNRVAD()
        frames = sliceable_deque([], 30)
        timeout=1
        minimum_capture=0.5
        _timeout_frames = 10
        stt_thread = None
        # periodlength is the length of a period in seconds
        period_length = 0.03
        _minimum_capture = round((timeout + minimum_capture) / period_length)
        last_voice_frame = 0
        recording = False
        recording_frames = []
        audio_processor.open_stream()
        try:
            while True:
                input_data = audio_processor.record()
                voice_detected = VAD._voice_detected(
                    input_data,
                    input_bits=self.input_bits,
                    recording=recording
                )
                frames.append(input_data)
                if not recording:
                    if(voice_detected):
                        # Voice activity detected, start recording and use
                        # the last 10 frames to start
                        # println(
                        #     "Started recording",
                        #     scroll=True
                        # )
                        recording = True
                        # Include the previous 10 frames in the recording.
                        # print(f"slice - max({len(frames)} - {_timeout_frames}, 0) = {max(len(frames)-_timeout_frames, 0)}")
                        recording_frames = frames[max(len(frames)-_timeout_frames, 0):]
                        last_voice_frame = len(recording_frames)
                else:
                    # We're recording
                    recording_frames.append(input_data)
                    if(voice_detected):
                        last_voice_frame = len(recording_frames)
                    if(last_voice_frame < (len(recording_frames) - _timeout_frames*2)):
                        # We have waited past the timeout number of frames
                        # so we believe the speaker has finished speaking.
                        if(len(recording_frames) > _minimum_capture):
                            println(
                                "Recorded {:.2f} seconds".format(
                                    len(recording_frames) * period_length
                                ),
                                self.displaywidth,
                                scroll=True
                            )
                            # put the audio in a queue and call the stt engine
                            self.recordings_queue.appendleft(recording_frames)
                            if not (stt_thread and hasattr(stt_thread, "is_alive") and stt_thread.is_alive()):
                                # start the thread
                                stt_thread = threading.Thread(
                                    target=self.stt
                                )
                                stt_thread.start()
                        frames.clear()
                        recording = False
                        recording_frames = []
                        last_voice_frame = 0
        except KeyboardInterrupt:
            println("Exiting...", self.displaywidth)
        finally:
            # Close the stream
            audio_processor.close_stream()


if __name__ == "__main__":
    Main().main()
