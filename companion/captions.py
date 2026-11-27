import threading
import time
from collections import deque

import numpy as np
from faster_whisper import WhisperModel


SAMPLE_RATE = 16_000
CAPTION_SECONDS = 15


class CaptionEngine:
    def __init__(self, model, speakers=None, translate_non_english=False):
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=4)
        self.speakers = speakers
        self.translate_non_english = translate_non_english
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

    def recognize(self, audio, language, mode):
        if self.translate_non_english:
            language, mode = "auto", "translate"
        turns = self.speakers.split(audio) if self.speakers else [(None, "speech", audio)]
        captions = []
        for speaker, kind, clip in turns:
            segments, info = self.model.transcribe(
                clip,
                language=None if language == "auto" else language,
                task=mode,
                beam_size=1,
                vad_filter=self.speakers is None or kind == "unassigned",
                condition_on_previous_text=False,
            )
            if self.translate_non_english and info.language == "en":
                continue
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if not text:
                continue
            self.sequence += 1
            captions.append({
                "id": self.sequence,
                "text": text,
                "speaker": speaker,
                "kind": kind,
                "language": info.language,
                "mode": mode,
                "timestamp": round(time.time(), 3),
            })
        with self.caption_lock:
            self.history.extend(captions)
        return captions

    def current(self):
        cutoff = time.time() - CAPTION_SECONDS
        with self.caption_lock:
            return [caption for caption in self.history if caption["timestamp"] > cutoff]
