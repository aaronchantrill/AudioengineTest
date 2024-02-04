import collections
import contextlib
import tempfile
import threading
import wave
from core import visualizations
from datetime import datetime


class Mic:
    def __init__(self, *args, **kwargs):
        self._input_device = kwargs['input_device']
        self.active_stt_plugin = kwargs['active_stt_plugin']
        self.recordings_queue = collections.deque([], maxlen=10)
        self.actions_queue = collections.deque([], maxlen=10)
        self.actions_thread = None
        self.Continue = True

    def add_to_queue(self, audio):
        self.recordings_queue.appendleft(audio)

    @contextlib.contextmanager
    def _write_frames_to_file(self, frames, volume):
        with tempfile.NamedTemporaryFile(
            mode='w+b',
            suffix=".wav",
            prefix=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        ) as f:
            wav_fp = wave.open(f, 'wb')
            wav_fp.setnchannels(self._input_device._input_channels)
            wav_fp.setsampwidth(int(self._input_device._input_bits / 8))
            wav_fp.setframerate(self._input_device._input_rate)
            fragment = b''.join(frames)
            if volume is not None:
                maxvolume = audioop.minmax(
                    fragment,
                    self._input_device._input_bits / 8
                )[1]
                fragment = audioop.mul(
                    fragment,
                    int(self._input_device._input_bits / 8),
                    volume * (2. ** 15) / maxvolume
                )

            wav_fp.writeframes(fragment)
            wav_fp.close()
            f.seek(0)
            yield f

    def listen(self):
        while True:
            try:
                audio = self.recordings_queue.pop()
                with self._write_frames_to_file(audio, None) as f:
                    transcription = self.active_stt_plugin.transcribe(f)[0]
                if len(transcription) > 0:
                    visualizations.run_visualization(
                        "output",
                        f"<< {transcription}"
                    )
                else:
                    visualizations.run_visualization(
                        "output",
                        f"<< <noise>"
                    )
                if any(map(lambda v: v in transcription, ["shut down", "shutdown", "turn off", "quit"])):
                    self.say("okay, quitting")
                    self.Continue = False
                if transcription.startswith("say "):
                    # start a speak thread
                    self.say("here is what you said to say")
                    self.say(transcription[4:])
            except IndexError:
                break

    def say(self, phrase):
        self.actions_queue.appendleft(lambda: self.tts(phrase))
        if not (self.actions_thread and hasattr(self.actions_thread, "is_alive") and self.actions_thread.is_alive()):
            # start the thread
            actions_thread = threading.Thread(
                target=self.process_actions
            )
            actions_thread.start()

    def process_actions(self):
        while True:
            try:
                action = self.actions_queue.pop()
                action()
            except IndexError:
                break

    def tts(self, phrase):
        visualizations.run_visualization(
            "output",
            f">> {phrase}"
        )
