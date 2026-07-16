import json
import os
import tempfile
import unittest
from unittest.mock import patch

import pysubs2

from src.subtitles import extract_subtitles, merge_subtitles


class SubtitleIntegrationTests(unittest.TestCase):
    def test_subtitle_extraction_uses_a_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "video.mkv")
            output = os.path.join(directory, "track.srt")
            open(source, "wb").close()

            def fake_run(command, check):
                extracted_path = command[-1].split(":", 1)[1]
                with open(extracted_path, "w", encoding="utf-8") as handle:
                    handle.write("1\n00:00:00,000 --> 00:00:01,000\ntext\n")

            with patch("src.subtitles.subprocess.run", side_effect=fake_run) as run:
                extract_subtitles(source, output, subtitle_track_index=2)
                extract_subtitles(source, output, subtitle_track_index=2)

            self.assertEqual(run.call_count, 1)
            self.assertTrue(os.path.isfile(f"{output}.manifest.json"))

    def test_existing_japanese_fixtures_merge_without_losing_events(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "merged.ass")
            merge_subtitles(
                base_subs_path="examples/japanese_translation.ass",
                second_subs_path=None,
                transcribed_subs_path="examples/japanese_transcription.ass",
                output_subs_path=output,
                detected_language="ja",
            )
            merged = pysubs2.load(output)
            self.assertEqual(len([event for event in merged if event.text.strip()]), 22)
            self.assertTrue(all(event.end > event.start for event in merged))

    def test_structured_words_split_a_segment_across_base_cues(self):
        with tempfile.TemporaryDirectory() as directory:
            base_path = os.path.join(directory, "base.srt")
            transcription_path = os.path.join(directory, "transcription.srt")
            result_path = os.path.join(directory, "transcription.json")
            output_path = os.path.join(directory, "merged.ass")

            base = pysubs2.SSAFile()
            base.append(pysubs2.SSAEvent(start=0, end=1000, text="First"))
            base.append(pysubs2.SSAEvent(start=1000, end=2000, text="Second"))
            base.save(base_path)
            transcription = pysubs2.SSAFile()
            transcription.append(pysubs2.SSAEvent(start=0, end=2000, text="hello world"))
            transcription.save(transcription_path)
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"segments": [{"words": [
                    {"start": 0.1, "end": 0.5, "word": " hello"},
                    {"start": 1.2, "end": 1.6, "word": " world"},
                ]}]}, handle)

            merge_subtitles(
                base_subs_path=base_path,
                second_subs_path=None,
                transcribed_subs_path=transcription_path,
                transcription_result_path=result_path,
                output_subs_path=output_path,
                detected_language="en",
            )
            merged = pysubs2.load(output_path)
            transcription_events = [event for event in merged if event.layer == 2]
            self.assertEqual([event.text for event in transcription_events], ["hello", "world"])
            self.assertTrue(all(event.end > event.start for event in transcription_events))


if __name__ == "__main__":
    unittest.main()
