import threading
import time
from collections import deque

import numpy as np
from faster_whisper import WhisperModel


SAMPLE_RATE = 16_000
CAPTION_SECONDS = 15
PORTUGUESE_MIN_CONFIDENCE = 0.50


class CaptionEngine:
    def __init__(self, model, speakers=None, portuguese_only=False):
        self.model = WhisperModel(
            model, device="cpu", compute_type="int8",
            cpu_threads=5 if portuguese_only else 4,
            num_workers=2 if portuguese_only else 1,
        )
        self.speakers = speakers
        self.portuguese_only = portuguese_only
        self.inference_lock = threading.Lock()
        self.caption_lock = threading.Lock()
        self.history = deque(maxlen=16)
        self.sequence = 0

    def transcribe(self, pcm, language, mode):
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if np.mean(np.square(audio)) < 0.000001:
            return []
        if not self.inference_lock.acquire(blocking=False):
            raise BlockingIOError("The speech model is busy")
        try:
            return self.recognize(audio, language, mode)
        finally:
            self.inference_lock.release()

    def decode(self, clip, language, mode, vad_filter):
        if self.portuguese_only:
            language, mode = "auto", "translate"
        options = {}
        if self.portuguese_only:
            options = {
                "without_timestamps": True,
                "no_repeat_ngram_size": 4,
            }
        segments, info = self.model.transcribe(
            clip, language=None if language == "auto" else language,
            task=mode, beam_size=2 if self.portuguese_only else 1,
            vad_filter=vad_filter, condition_on_previous_text=False, temperature=0.0,
            **options,
        )
        if self.portuguese_only and (
            info.language != "pt" or info.language_probability < PORTUGUESE_MIN_CONFIDENCE
        ):
            return "", info.language
        return " ".join(segment.text.strip() for segment in segments).strip(), info.language

    def recognize(self, audio, language, mode):
        turns = self.speakers.split(audio) if self.speakers else [(None, "speech", audio)]
        captions = []
        for speaker, kind, clip in turns:
            text, detected = self.decode(clip, language, mode, self.speakers is None or kind == "unassigned")
            if text:
                captions.append({
                    "text": text, "speaker": speaker, "kind": kind, "language": detected,
                    "mode": "translate" if self.portuguese_only else mode,
                })
        return self.publish(captions)

    def publish(self, captions, replace=False):
        with self.caption_lock:
            for row in captions:
                if replace:
                    key = (row["speaker"], row["kind"])
                    self.history = deque(
                        (previous for previous in self.history
                         if (previous["speaker"], previous["kind"]) != key),
                        maxlen=self.history.maxlen,
                    )
                self.sequence += 1
                row.update(id=self.sequence, timestamp=round(time.time(), 3))
                self.history.append(row)
        return captions

    def current(self):
        cutoff = time.time() - CAPTION_SECONDS
        with self.caption_lock:
            return [caption for caption in self.history if caption["timestamp"] > cutoff]
