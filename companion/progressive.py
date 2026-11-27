"""Rolling translation hypotheses and recovery of overlapping speaker audio."""

from concurrent.futures import ThreadPoolExecutor
from itertools import takewhile
from pathlib import Path

import numpy as np

from .captions import SAMPLE_RATE


HOP_SAMPLES = SAMPLE_RATE * 4 // 5
CONTEXT_SAMPLES = SAMPLE_RATE * 5
MIN_SPEECH = SAMPLE_RATE * 3 // 5
RECENT_SPEECH = SAMPLE_RATE * 3 // 2

SEPARATOR_FILE = "convtasnet_sepnoisy_16k.onnx"
SEPARATOR_REPO = "iamdgarcia/ConvTasNet_Libri2Mix_sepnoisy_16k-onnx"
SEPARATOR_REVISION = "da34e6715813c8825f2b238977b35ebdf21e3c7e"


class OverlapSeparator:
    def __init__(self, models):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        local = Path(models) / SEPARATOR_FILE
        path = local if local.is_file() else hf_hub_download(
            SEPARATOR_REPO, SEPARATOR_FILE, revision=SEPARATOR_REVISION,
        )
        options = ort.SessionOptions()
        options.intra_op_num_threads = 3
        self.session = ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def split(self, audio):
        tracks = self.session.run(None, {self.input_name: audio[None]})[0]
        return tracks[0, :, :len(audio)]


class ProgressiveCaptions:
    def __init__(self, engine, tracker, separator=None):
        if separator and tracker is None:
            raise ValueError("Overlap separation requires a speaker tracker.")
        self.engine = engine
        self.tracker = tracker
        self.separator = separator
        self.previous = {}

    def clips(self, audio, offset):
        turns = self.tracker.track_window(audio, offset) if self.tracker else []
        if not turns:
            return {(None, "unassigned"): audio}

        by_speaker = {}
        for start, end, speaker, kind in turns:
            part = audio[start:end]
            if kind == "overlap" and self.separator and len(part) >= MIN_SPEECH:
                padding = SAMPLE_RATE // 6
                left, right = max(0, start - padding), min(len(audio), end + padding)
                isolated = self.separator.split(audio[left:right])
                used = set()
                threshold = np.mean(np.square(part)) * 0.03
                for source in sorted(isolated, key=lambda track: -np.mean(np.square(track))):
                    clean = source[start - left:end - left]
                    if np.mean(np.square(clean)) < threshold:
                        continue
                    vector = self.tracker.embedding(clean)
                    if vector is None:
                        continue
                    identity = self.tracker.match(vector, used)
                    self.tracker.remember(identity, vector)
                    used.add(identity)
                    by_speaker.setdefault((identity, "speech"), []).append((start, end, clean))
                if used:
                    continue
            by_speaker.setdefault((speaker, kind), []).append((start, end, part))

        recent = []
        for key, turns in by_speaker.items():
            if turns[-1][1] < len(audio) - RECENT_SPEECH:
                continue
            last = turns[-1][1]
            clips = []
            for start, end, part in reversed(turns):
                if last - end > RECENT_SPEECH:
                    break
                clips.append(part)
                last = start
            clip = np.concatenate(clips[::-1])
            if len(clip) >= MIN_SPEECH:
                recent.append((turns[-1][1], key, clip))
        return {key: clip for _, key, clip in sorted(recent, key=lambda row: row[0])[-3:]}

    def update(self, audio, offset, executor: ThreadPoolExecutor):
        if len(audio) < MIN_SPEECH or np.mean(np.square(audio[-HOP_SAMPLES:])) < 0.000001:
            return []
        clips = self.clips(audio, offset)
        pending = [
            (key, executor.submit(self.engine.decode, clip, "auto", "translate", True))
            for key, clip in clips.items()
        ]
        # Both model workers can decode independently. Publish in speaking order.
        rows = []
        for key, future in pending:
            text, language = future.result()
            if not text:
                continue
            words = text.split()
            previous = self.previous.get(key)
            stable = 0
            if previous and offset + len(audio) - previous[1] < CONTEXT_SAMPLES:
                stable = sum(1 for _ in takewhile(
                    lambda pair: pair[0].casefold() == pair[1].casefold(),
                    zip(previous[0], words),
                ))
            self.previous[key] = (words, offset + len(audio))
            speaker, kind = key
            rows.append({
                "text": text, "language": language, "speaker": speaker, "kind": kind,
                "mode": "translate", "stable_words": stable,
            })
        self.previous = {
            key: value for key, value in self.previous.items()
            if offset + len(audio) - value[1] < CONTEXT_SAMPLES
        }
        return self.engine.publish(rows, replace=True)


def stream_audio(source, engine, tracker, separator, stopped):
    from collections import deque
    from threading import Condition, Thread

    pending = deque(maxlen=14)
    available = Condition()
    received = 0
    closed = False

    def read_audio():
        nonlocal received, closed
        try:
            while not stopped.is_set() and (data := source.read(HOP_SAMPLES)):
                if len(data) % 2:
                    break
                frame = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
                with available:
                    received += len(frame)
                    pending.append(frame)
                    available.notify()
        finally:
            with available:
                closed = True
                available.notify()

    tracker = ProgressiveCaptions(engine, tracker, separator)
    Thread(target=read_audio, daemon=True).start()
    cursor = 0
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            while not stopped.is_set():
                with available:
                    available.wait_for(
                        lambda: stopped.is_set() or closed or received - cursor >= HOP_SAMPLES,
                        timeout=0.2,
                    )
                    if stopped.is_set() or (closed and received == cursor):
                        break
                    if not closed and received - cursor < HOP_SAMPLES:
                        continue
                    cursor = received
                    audio = np.concatenate(pending)[-CONTEXT_SAMPLES:]
                tracker.update(audio, cursor - len(audio), pool)
    finally:
        stopped.set()
