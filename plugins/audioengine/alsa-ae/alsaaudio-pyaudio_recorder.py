# -*- coding: utf-8 -*-
import audioop
import math
import sys
import unittest
from naomi import plugin
from naomi import profile
from naomi import visualizations

try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    import alsaaudio
except ImportError:
    alsaaudio = None

class AudioProcessor:
    def __init__(self, library, input_device='default', sample_rate=16000, chunk_size=1024):
        self.library = library
        self.input_device = input_device
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size

        if self.library == 'pyaudio':
            self.stream = pyaudio.PyAudio().open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                input=True,
                input_device_index=input_device,
                frames_per_buffer=chunk_size
            )
        elif self.library == 'pyalsaaudio':
            self.stream = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL, input_device)
            self.stream.setchannels(1)
            self.stream.setrate(sample_rate)
            self.stream.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            self.stream.setperiodsize(chunk_size)
        self.VAD = SNRVAD()

    def run(self):
        try:
            recording = False
            while True:
                input_data = self.stream.read(self.chunk_size)
                # Process the input data as needed
                recording = self.VAD._voice_detected(input_data, recording=recording)
                print("Processing input data...")
        except KeyboardInterrupt:
            pass
        finally:
            # Close the stream
            self.stream.close()


def main():
    if pyaudio is None and alsaaudio is None:
        print("Error: Both pyaudio and pyalsaaudio libraries are not installed.")
        sys.exit(1)

    available_libraries = []
    if pyaudio:
        available_libraries.append('pyaudio')
    if alsaaudio:
        available_libraries.append('pyalsaaudio')

    print("Available audio libraries:", available_libraries)

    library_choice = input("Choose an audio library ({}): ".format("/".join(available_libraries)))

    if library_choice not in available_libraries:
        print("Invalid choice. Exiting.")
        sys.exit(1)

    input_device = input("Enter input device index or 'default': ")

    audio_processor = AudioProcessor(library=library_choice, input_device=input_device)

    print("Streaming... Press Ctrl+C to stop.")

    audio_processor.run()

if __name__ == "__main__":
    main()
