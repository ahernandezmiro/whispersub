import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from src.cache import build_manifest, read_manifest, write_manifest
from src.transcription import (
    _normalize_language,
    _select_language,
    transcribe_with_whisper,
)


class _FakeResult:
    language = "en"

    def split_by_length(self, max_words):
        self.max_words = max_words

    def save_as_json(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"language": self.language, "segments": []}, handle)

    def to_srt_vtt(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")


class _FakeModel:
    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.feature_extractor = types.SimpleNamespace(n_samples=10)

    def transcribe(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            error, self.error = self.error, None
            raise error
        return _FakeResult()

    def detect_language(self, audio):
        return "en", 1.0, [("en", 1.0)]


class _FakeDetectionModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.feature_extractor = types.SimpleNamespace(n_samples=10)

    def detect_language(self, audio):
        self.calls.append(audio)
        return self.responses.pop(0)


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.decode_patch = patch(
            "src.transcription._decode_audio",
            return_value=np.arange(40, dtype=np.float32),
        )
        self.decode_patch.start()
        self.addCleanup(self.decode_patch.stop)

    def _paths(self, directory):
        audio = os.path.join(directory, "audio.wav")
        open(audio, "wb").close()
        return (
            audio,
            os.path.join(directory, "result.srt"),
            os.path.join(directory, "language.txt"),
            os.path.join(directory, "result.json"),
        )

    def test_normalizes_iso_container_language_code(self):
        self.assertEqual(_normalize_language("jpn"), "ja")
        self.assertEqual(_normalize_language("eng"), "en")
        self.assertEqual(_normalize_language("ja"), "ja")
        self.assertIsNone(_normalize_language("und"))

    def test_explicit_language_override_skips_detection(self):
        model = _FakeDetectionModel([])

        with patch("src.transcription._decode_audio") as decode:
            selection = _select_language(
                model,
                "audio.wav",
                requested_language="ja",
                metadata_language="kor",
            )

        self.assertEqual(selection.language, "ja")
        self.assertEqual(selection.source, "override")
        decode.assert_not_called()
        self.assertEqual(model.calls, [])

    def test_supported_metadata_language_wins_with_high_confidence(self):
        model = _FakeDetectionModel([
            ("ja", 0.90, [("ja", 0.90), ("ko", 0.10)]),
            ("ja", 0.80, [("ja", 0.80), ("ko", 0.20)]),
            ("ja", 0.70, [("ja", 0.70), ("ko", 0.30)]),
        ])

        with patch(
            "src.transcription._decode_audio",
            return_value=np.arange(40, dtype=np.float32),
        ):
            selection = _select_language(
                model,
                "audio.wav",
                metadata_language="jpn",
            )

        self.assertEqual(selection.language, "ja")
        self.assertEqual(selection.source, "metadata")
        self.assertAlmostEqual(selection.confidence, 0.8)
        self.assertEqual(len(model.calls), 3)

    def test_weak_metadata_hint_falls_back_to_weighted_vote(self):
        model = _FakeDetectionModel([
            ("ja", 0.70, [("ja", 0.70), ("ko", 0.20), ("en", 0.10)]),
            ("ko", 0.60, [("ko", 0.60), ("ja", 0.35), ("en", 0.05)]),
            ("ja", 0.80, [("ja", 0.80), ("ko", 0.10), ("en", 0.10)]),
        ])

        with patch(
            "src.transcription._decode_audio",
            return_value=np.arange(40, dtype=np.float32),
        ):
            selection = _select_language(
                model,
                "audio.wav",
                metadata_language="kor",
            )

        self.assertEqual(selection.language, "ja")
        self.assertEqual(selection.source, "weighted-vote")
        self.assertAlmostEqual(selection.confidence, (0.70 + 0.35 + 0.80) / 3)

    def test_gpu_transcription_does_not_enable_lossy_batched_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            model = _FakeModel()
            stable = types.SimpleNamespace(load_faster_whisper=lambda *args, **kwargs: model)
            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", return_value=("cuda", "large-v3")), \
                 patch("src.transcription._package_version", return_value="test"):
                transcribe_with_whisper(*paths[:3], result_json_path=paths[3])

            self.assertNotIn("batch_size", model.calls[0])

    def test_transcription_disables_previous_text_conditioning(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            model = _FakeModel()
            stable = types.SimpleNamespace(load_faster_whisper=lambda *args, **kwargs: model)
            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", return_value=("cuda", "large-v3")), \
                 patch("src.transcription._package_version", return_value="test"):
                transcribe_with_whisper(*paths[:3], result_json_path=paths[3])

            self.assertIs(model.calls[0]["condition_on_previous_text"], False)
            self.assertIs(
                read_manifest(paths[3])["config"]["condition_on_previous_text"],
                False,
            )

    def test_batched_transcription_cache_is_invalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            with open(paths[3], "w", encoding="utf-8") as handle:
                json.dump({"language": "en", "segments": []}, handle)
            write_manifest(
                paths[3],
                build_manifest(
                    "transcription",
                    paths[0],
                    {"inference_mode": "batched", "batch_policy": [8, 4, 2, 1]},
                ),
            )
            model = _FakeModel()
            stable = types.SimpleNamespace(load_faster_whisper=lambda *args, **kwargs: model)

            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", return_value=("cpu", "medium")), \
                 patch("src.transcription._package_version", return_value="test"):
                transcribe_with_whisper(*paths[:3], result_json_path=paths[3])

            self.assertEqual(len(model.calls), 1)
            self.assertEqual(
                read_manifest(paths[3])["config"]["inference_mode"],
                "sequential",
            )

    def test_structured_result_cache_skips_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            model = _FakeModel()
            load_count = []

            def load(*args, **kwargs):
                load_count.append(1)
                return model

            stable = types.SimpleNamespace(
                load_faster_whisper=load,
                WhisperResult=lambda path: _FakeResult(),
            )
            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", return_value=("cpu", "medium")), \
                 patch("src.transcription._package_version", return_value="test"):
                transcribe_with_whisper(*paths[:3], model_name="turbo", result_json_path=paths[3])
                transcribe_with_whisper(*paths[:3], model_name="turbo", result_json_path=paths[3])
            self.assertEqual(len(load_count), 1)

    def test_language_override_invalidates_transcription_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            model = _FakeModel()
            stable = types.SimpleNamespace(
                load_faster_whisper=lambda *args, **kwargs: model,
                WhisperResult=lambda path: _FakeResult(),
            )
            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", return_value=("cpu", "medium")), \
                 patch("src.transcription._package_version", return_value="test"):
                transcribe_with_whisper(
                    *paths[:3],
                    language="ja",
                    result_json_path=paths[3],
                )
                transcribe_with_whisper(
                    *paths[:3],
                    language="ko",
                    result_json_path=paths[3],
                )

            self.assertEqual(len(model.calls), 2)
            self.assertEqual(
                [call["language"] for call in model.calls],
                ["ja", "ko"],
            )
            self.assertEqual(
                read_manifest(paths[3])["config"]["requested_language"],
                "ko",
            )

    def test_cpu_fallback_preserves_explicit_model(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            loaded = []

            def load(model_name, **kwargs):
                loaded.append((model_name, kwargs["device"]))
                if kwargs["device"] == "cuda":
                    return _FakeModel(RuntimeError("CUDA driver failure"))
                return _FakeModel()

            stable = types.SimpleNamespace(load_faster_whisper=load)
            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", side_effect=[("cuda", "large-v2"), ("cpu", "medium")]), \
                 patch("src.transcription._clear_cuda_cache"), \
                 patch("src.transcription._package_version", return_value="test"):
                transcribe_with_whisper(*paths[:3], model_name="turbo", result_json_path=paths[3])
            self.assertEqual(loaded, [("turbo", "cuda"), ("turbo", "cpu")])

    def test_voice_separation_uses_cached_vocals_as_model_input(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            vocals = os.path.join(directory, "audio_vocals.wav")
            model = _FakeModel()
            stable = types.SimpleNamespace(load_faster_whisper=lambda *args, **kwargs: model)

            with patch.dict(sys.modules, {"stable_whisper": stable}), \
                 patch("src.transcription.get_optimal_device_and_model", return_value=("cuda", "large-v2")), \
                 patch("src.transcription._package_version", return_value="test"), \
                 patch("src.transcription.separate_vocals", return_value=vocals) as separate:
                transcribe_with_whisper(
                    *paths[:3],
                    model_name="turbo",
                    voice_separation=True,
                    result_json_path=paths[3],
                )

            separate.assert_called_once_with(paths[0], vocals, device="cuda")
            self.assertEqual(model.calls[0]["audio"], vocals)
            self.assertNotIn("denoiser", model.calls[0])


if __name__ == "__main__":
    unittest.main()
