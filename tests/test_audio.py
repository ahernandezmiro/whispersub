import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.audio import extract_audio, get_audio_track_language, separate_vocals


class AudioExtractionTests(unittest.TestCase):
    def test_reads_language_from_selected_audio_stream(self):
        probe_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({
                "streams": [
                    {"index": 0, "codec_type": "video", "tags": {}},
                    {
                        "index": 1,
                        "codec_type": "audio",
                        "tags": {"language": "jpn"},
                    },
                ],
            }),
            stderr="",
        )

        with patch("src.audio.subprocess.run", return_value=probe_result) as run:
            language = get_audio_track_language("video.mkv", audio_track_index=1)

        self.assertEqual(language, "jpn")
        self.assertIn("ffprobe", run.call_args.args[0][0])

    def test_missing_audio_language_metadata_is_nonfatal(self):
        probe_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"streams": [{"index": 1, "codec_type": "audio"}]}',
            stderr="",
        )

        with patch("src.audio.subprocess.run", return_value=probe_result):
            self.assertIsNone(
                get_audio_track_language("video.mkv", audio_track_index=1)
            )

    def test_extracts_16khz_mono_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "video.mkv")
            output = os.path.join(directory, "audio.wav")
            open(source, "wb").close()
            sample_rates = []

            def fake_run(command, check):
                sample_rates.append(command[command.index("-ar") + 1])
                self.assertEqual(command[command.index("-ac") + 1], "1")
                with open(command[-1], "wb") as handle:
                    handle.write(b"wav")

            with patch("src.audio.subprocess.run", side_effect=fake_run) as run:
                extract_audio(source, output, audio_track_index=1)
                extract_audio(source, output, audio_track_index=1)
                extract_audio(source, output, audio_track_index=1, sample_rate=8000)

            self.assertEqual(run.call_count, 2)
            self.assertEqual(sample_rates, ["16000", "8000"])
            self.assertTrue(os.path.isfile(output))
            self.assertTrue(os.path.isfile(f"{output}.manifest.json"))

    def test_separates_and_caches_resampled_vocals(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "audio.wav")
            output = os.path.join(directory, "audio_vocals.wav")
            open(source, "wb").close()

            def fake_run(command, check):
                if "demucs" in command:
                    model = command[command.index("-n") + 1]
                    demucs_output = command[command.index("-o") + 1]
                    stem_dir = os.path.join(demucs_output, model, "audio")
                    os.makedirs(stem_dir)
                    with open(os.path.join(stem_dir, "vocals.wav"), "wb") as handle:
                        handle.write(b"stem")
                else:
                    self.assertEqual(command[command.index("-ar") + 1], "16000")
                    self.assertEqual(command[command.index("-ac") + 1], "1")
                    with open(command[-1], "wb") as handle:
                        handle.write(b"wav")

            with patch("src.audio.subprocess.run", side_effect=fake_run) as run:
                self.assertEqual(separate_vocals(source, output, device="cuda"), output)
                self.assertEqual(separate_vocals(source, output, device="cpu"), output)

            self.assertEqual(run.call_count, 2)
            self.assertTrue(os.path.isfile(output))
            self.assertTrue(os.path.isfile(f"{output}.manifest.json"))


if __name__ == "__main__":
    unittest.main()
