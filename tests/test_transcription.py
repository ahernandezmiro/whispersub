import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from src.cache import build_manifest, read_manifest, write_manifest
from src.transcription import transcribe_with_whisper


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

    def transcribe(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            error, self.error = self.error, None
            raise error
        return _FakeResult()


class TranscriptionTests(unittest.TestCase):
    def _paths(self, directory):
        audio = os.path.join(directory, "audio.wav")
        open(audio, "wb").close()
        return (
            audio,
            os.path.join(directory, "result.srt"),
            os.path.join(directory, "language.txt"),
            os.path.join(directory, "result.json"),
        )

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
