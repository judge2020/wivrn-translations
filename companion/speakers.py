from pathlib import Path

import numpy as np
import sherpa_onnx as sherpa

from .captions import SAMPLE_RATE


class SpeakerTracker:
    def __init__(self, directory):
        directory = Path(directory)
        segmentation = directory / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
        embedding = directory / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
        for model in (segmentation, embedding):
            if not model.is_file():
                raise ValueError(f"Missing speaker model: {model}. See the README for downloads.")
        embedding_config = sherpa.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=1)
        config = sherpa.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(segmentation), window_shift_ratio=0.25
                ),
                num_threads=2,
            ),
            embedding=embedding_config,
            clustering=sherpa.FastClusteringConfig(num_clusters=-1, threshold=0.5),
            min_duration_on=0.35,
            min_duration_off=0.20,
        )
        if not config.validate():
            raise ValueError("Invalid speaker model configuration.")
        self.diarization = sherpa.OfflineSpeakerDiarization(config)
        self.embedder = sherpa.SpeakerEmbeddingExtractor(embedding_config)
        self.profiles = {}
        self.next_id = 1
        self.context = np.empty(0, dtype=np.float32)
        self.previous_turns = []

    def partition(self, audio):
        segments = self.diarization.process(audio).sort_by_start_time()
        spans = [
            (max(0, round(s.start * SAMPLE_RATE)), min(len(audio), round(s.end * SAMPLE_RATE)), s.speaker)
            for s in segments
        ]
        edges = sorted({point for start, end, _ in spans for point in (start, end)})
        turns = []
        for start, end in zip(edges, edges[1:]):
            active = {speaker for left, right, speaker in spans if left < end and right > start}
            if not active:
                continue
            speaker = next(iter(active)) if len(active) == 1 else None
            if turns and turns[-1][1] == start and turns[-1][2] == speaker:
                turns[-1] = (turns[-1][0], end, speaker)
            else:
                turns.append((start, end, speaker))
        return turns

    def label(self, audio, turns, boundary):
        clips = {}
        for start, end, speaker in turns:
            if speaker is not None:
                clips.setdefault(speaker, []).append(audio[start:end])

        overlap_scores = {}
        for start, end, speaker in turns:
            if speaker is None or start >= boundary:
                continue
            for left, right, identity in self.previous_turns:
                overlap = min(end, right) - max(start, left)
                if overlap > 0:
                    pair = (speaker, identity)
                    overlap_scores[pair] = overlap_scores.get(pair, 0) + overlap

        labels = {}
        matched = set()
        for (speaker, identity), count in sorted(overlap_scores.items(), key=lambda item: -item[1]):
            if count >= SAMPLE_RATE * 0.6 and speaker not in labels and identity not in matched:
                labels[speaker] = identity
                matched.add(identity)
        for speaker, samples in clips.items():
            speech = np.concatenate(samples)
            if len(speech) < SAMPLE_RATE * 0.85:
                continue
            stream = self.embedder.create_stream()
            stream.accept_waveform(SAMPLE_RATE, speech)
            stream.input_finished()
            if not self.embedder.is_ready(stream):
                continue
            vector = np.asarray(self.embedder.compute(stream))
            norm = np.linalg.norm(vector)
            if not np.isfinite(norm) or norm == 0:
                continue
            vector /= norm
            identity = labels.get(speaker)
            if identity is None:
                candidates = [
                    (np.dot(previous, vector), key)
                    for key, previous in self.profiles.items() if key not in matched
                ]
                similarity, key = max(candidates, default=(0, None))
                if similarity >= 0.57:
                    identity = key
                else:
                    identity = self.next_id
                    self.next_id += 1
            if identity in self.profiles:
                vector = 0.8 * self.profiles.pop(identity) + 0.2 * vector
                vector /= np.linalg.norm(vector)
            self.profiles[identity] = vector
            matched.add(identity)
            labels[speaker] = identity

        while len(self.profiles) > 16:
            del self.profiles[next(iter(self.profiles))]
        return labels

    def split(self, audio):
        boundary = len(self.context)
        combined = np.concatenate((self.context, audio))
        turns = self.partition(combined)
        labels = self.label(combined, turns, boundary)
        retained = max(0, len(combined) - 12 * SAMPLE_RATE)
        self.context = combined[retained:]
        self.previous_turns = [
            (max(0, start - retained), end - retained, labels[speaker])
            for start, end, speaker in turns if end > retained and speaker in labels
        ]
        result = []
        for start, end, speaker in turns:
            start = max(start, boundary)
            if end - start < SAMPLE_RATE * 0.55:
                continue
            kind = "overlap" if speaker is None else "speech"
            result.append((labels.get(speaker), kind, combined[start:end]))
        return result or [(None, "unassigned", audio)]
