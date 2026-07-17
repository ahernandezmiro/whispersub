import json
import os
import tempfile
import unittest
from unittest.mock import patch

import pysubs2

from src.subtitles import extract_subtitles, merge_subtitles


class SubtitleIntegrationTests(unittest.TestCase):
    def test_transcription_only_word_level_render_needs_no_base_track(self):
        with tempfile.TemporaryDirectory() as directory:
            transcription_path = os.path.join(directory, "transcription.srt")
            output_path = os.path.join(directory, "transcription.ass")
            transcription = pysubs2.SSAFile()
            transcription.append(
                pysubs2.SSAEvent(start=100, end=900, text="spoken text")
            )
            transcription.save(transcription_path)

            merge_subtitles(
                base_subs_path=None,
                second_subs_path=None,
                transcribed_subs_path=transcription_path,
                output_subs_path=output_path,
                detected_language="en",
                highlight_current_word=True,
            )

            rendered = pysubs2.load(output_path)
            self.assertEqual(
                [event.text for event in rendered if event.layer == 2],
                ["spoken text"],
            )

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
            self.assertEqual(len({event.style for event in transcription_events}), 1)

    def test_generated_styles_ignore_overlay_identity_and_preserve_source_metadata(self):
        class Converter:
            def romanize(self, text):
                return f'rom {text}'

        with tempfile.TemporaryDirectory() as directory:
            base_path = os.path.join(directory, 'base.ass')
            transcription_path = os.path.join(directory, 'transcription.srt')
            output_path = os.path.join(directory, 'merged.ass')

            base = pysubs2.SSAFile()
            base.info['PlayResX'] = '640'
            base.info['PlayResY'] = '360'
            base.styles['Show_Title'] = pysubs2.SSAStyle(
                fontsize=32,
                alignment=8,
                primarycolor=pysubs2.Color(255, 0, 0),
            )
            base.styles['Main'] = pysubs2.SSAStyle(
                fontsize=22,
                alignment=2,
                primarycolor=pysubs2.Color(0, 80, 255),
            )
            base.append(pysubs2.SSAEvent(
                start=0,
                end=2000,
                text=r'{\pos(320,35)}Episode One',
                style='Show_Title',
                name='source-title',
                marginl=17,
                effect='Banner',
            ))
            base.append(pysubs2.SSAEvent(
                start=0,
                end=2000,
                text='Translated dialogue',
                style='Main',
            ))
            base.save(base_path)

            transcription = pysubs2.SSAFile()
            transcription.append(pysubs2.SSAEvent(
                start=0,
                end=2000,
                text='spoken dialogue',
            ))
            transcription.save(transcription_path)

            with patch('src.subtitles.romanization_converter', return_value=Converter()):
                merge_subtitles(
                    base_subs_path=base_path,
                    second_subs_path=None,
                    transcribed_subs_path=transcription_path,
                    output_subs_path=output_path,
                    detected_language='ja',
                    need_romanization=True,
                )

            merged = pysubs2.load(output_path)
            title = next(event for event in merged if 'Episode One' in event.text)
            self.assertEqual(title.style, 'Show_Title')
            self.assertEqual(title.name, 'source-title')
            self.assertEqual(title.marginl, 17)
            self.assertEqual(title.effect, 'Banner')

            transcription_event = next(event for event in merged if event.layer == 2)
            romanized_event = next(event for event in merged if event.layer == 3)
            self.assertNotIn('Show_Title', transcription_event.style)
            self.assertNotIn('Main', transcription_event.style)
            self.assertNotIn('Show_Title', romanized_event.style)
            self.assertNotIn('Main', romanized_event.style)
            transcription_color = merged.styles[transcription_event.style].primarycolor
            self.assertEqual(
                (
                    transcription_color.r,
                    transcription_color.g,
                    transcription_color.b,
                ),
                (255, 255, 255),
            )
            romanized_color = merged.styles[romanized_event.style].primarycolor
            self.assertEqual(
                (romanized_color.r, romanized_color.g, romanized_color.b),
                (188, 188, 188),
            )

    def test_merge_only_preserves_conflicting_source_style_definitions(self):
        with tempfile.TemporaryDirectory() as directory:
            base_path = os.path.join(directory, 'base.ass')
            second_path = os.path.join(directory, 'second.ass')
            output_path = os.path.join(directory, 'merged.ass')

            base = pysubs2.SSAFile()
            base.styles['Shared'] = pysubs2.SSAStyle(
                primarycolor=pysubs2.Color(255, 0, 0)
            )
            base.append(pysubs2.SSAEvent(
                start=0, end=1000, text='base', style='Shared'
            ))
            base.save(base_path)

            second = pysubs2.SSAFile()
            second.styles['Shared'] = pysubs2.SSAStyle(
                primarycolor=pysubs2.Color(0, 255, 0)
            )
            second.append(pysubs2.SSAEvent(
                start=0, end=1000, text='second', style='Shared'
            ))
            second.save(second_path)

            merge_subtitles(
                base_subs_path=base_path,
                second_subs_path=second_path,
                transcribed_subs_path=None,
                output_subs_path=output_path,
                detected_language='en',
            )
            merged = pysubs2.load(output_path)
            base_event = next(event for event in merged if event.text == 'base')
            second_event = next(event for event in merged if event.text == 'second')
            self.assertNotEqual(base_event.style, second_event.style)
            base_color = merged.styles[base_event.style].primarycolor
            second_color = merged.styles[second_event.style].primarycolor
            self.assertEqual((base_color.r, base_color.g, base_color.b), (255, 0, 0))
            self.assertEqual((second_color.r, second_color.g, second_color.b), (0, 255, 0))

    def test_generated_style_overrides_remain_authoritative(self):
        class Converter:
            def romanize(self, text):
                return 'romanized'

        with tempfile.TemporaryDirectory() as directory:
            transcription_path = os.path.join(directory, 'transcription.srt')
            output_path = os.path.join(directory, 'merged.ass')
            transcription = pysubs2.SSAFile()
            transcription.append(pysubs2.SSAEvent(
                start=0, end=1000, text='spoken'
            ))
            transcription.save(transcription_path)

            with patch('src.subtitles.romanization_converter', return_value=Converter()):
                merge_subtitles(
                    base_subs_path=None,
                    second_subs_path=None,
                    transcribed_subs_path=transcription_path,
                    output_subs_path=output_path,
                    detected_language='ja',
                    need_romanization=True,
                    style_config={
                        'transcription': {
                            'fontname': 'Tahoma',
                            'fontsize': '*1.5',
                            'primarycolor': '102030',
                            'secondarycolor': '102030',
                        },
                        'romanization': {
                            'primarycolor': '123456',
                            'secondarycolor': '123456',
                        },
                    },
                )
            merged = pysubs2.load(output_path)
            trans_event = next(event for event in merged if event.layer == 2)
            rom_event = next(event for event in merged if event.layer == 3)
            trans_style = merged.styles[trans_event.style]
            rom_style = merged.styles[rom_event.style]
            self.assertEqual(trans_style.fontname, 'Tahoma')
            self.assertEqual(trans_style.fontsize, 24)
            self.assertEqual(
                (
                    trans_style.primarycolor.r,
                    trans_style.primarycolor.g,
                    trans_style.primarycolor.b,
                ),
                (16, 32, 48),
            )
            self.assertEqual(
                (rom_style.primarycolor.r, rom_style.primarycolor.g, rom_style.primarycolor.b),
                (18, 52, 86),
            )

    def test_only_high_confidence_dialogue_can_select_the_top_zone(self):
        for base_style_name, expected_alignment in (
            ('Fancy', 2),
            ('Main_Top', 8),
        ):
            with self.subTest(base_style_name=base_style_name):
                with tempfile.TemporaryDirectory() as directory:
                    base_path = os.path.join(directory, 'base.ass')
                    transcription_path = os.path.join(directory, 'transcription.srt')
                    output_path = os.path.join(directory, 'merged.ass')
                    base = pysubs2.SSAFile()
                    base.styles[base_style_name] = pysubs2.SSAStyle(alignment=8)
                    base.append(pysubs2.SSAEvent(
                        start=0,
                        end=1000,
                        text='source',
                        style=base_style_name,
                    ))
                    base.save(base_path)
                    transcription = pysubs2.SSAFile()
                    transcription.append(pysubs2.SSAEvent(
                        start=0, end=1000, text='spoken'
                    ))
                    transcription.save(transcription_path)
                    merge_subtitles(
                        base_subs_path=base_path,
                        second_subs_path=None,
                        transcribed_subs_path=transcription_path,
                        output_subs_path=output_path,
                        detected_language='en',
                    )
                    merged = pysubs2.load(output_path)
                    event = next(item for item in merged if item.layer == 2)
                    self.assertEqual(
                        int(merged.styles[event.style].alignment),
                        expected_alignment,
                    )


if __name__ == "__main__":
    unittest.main()
