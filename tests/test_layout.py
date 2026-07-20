import unittest
from unittest.mock import patch

import pysubs2

from src.layout import (
    EventRole,
    FallbackTextMeasurer,
    FontAwareTextMeasurer,
    LayoutEvent,
    ObstacleIndex,
    Rect,
    TextExtent,
    classify_event_role,
    estimate_event_box,
    plan_generated_layout,
)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.transcription_style = pysubs2.SSAStyle(
            fontname='Definitely Missing Font',
            fontsize=20,
            marginv=24,
            alignment=2,
            outline=1,
            shadow=1,
        )
        self.romanization_style = pysubs2.SSAStyle(
            fontname='Definitely Missing Font',
            fontsize=14,
            marginv=50,
            alignment=2,
            outline=1,
            shadow=1,
        )

    def test_role_classifier_keeps_overlays_from_donating_layout(self):
        self.assertEqual(
            classify_event_role('Episode 1', 'Show_Title', 8),
            EventRole.OVERLAY,
        )
        self.assertEqual(
            classify_event_role(r'{\pos(100,40)}Store', 'Default', 2),
            EventRole.OVERLAY,
        )
        self.assertEqual(
            classify_event_role('Hello', 'Main_Top', 8),
            EventRole.DIALOGUE,
        )
        self.assertEqual(
            classify_event_role('Unlabelled', 'Fancy', 8),
            EventRole.UNKNOWN,
        )
        for style_name in ('Sign_Basic', 'Opening_Credit', 'ED', 'Next_Episode'):
            with self.subTest(style_name=style_name):
                self.assertEqual(
                    classify_event_role('overlay', style_name, 2),
                    EventRole.OVERLAY,
                )

    def test_fallback_measurement_accounts_for_wrapping_and_explicit_lines(self):
        measurer = FallbackTextMeasurer()
        short = measurer.measure('short', self.transcription_style, 200)
        wrapped = measurer.measure('word ' * 40, self.transcription_style, 200)
        explicit = measurer.measure(r'one\Ntwo\Nthree\Nfour', self.transcription_style, 200)
        self.assertGreater(wrapped.height, short.height)
        self.assertEqual(explicit.lines, 4)
        self.assertGreater(explicit.height, short.height)

    def test_missing_font_uses_fallback_without_failing(self):
        extent = FontAwareTextMeasurer().measure(
            'still measurable', self.transcription_style, 200
        )
        self.assertGreater(extent.width, 0)
        self.assertGreater(extent.height, 0)

    def test_measurement_failure_uses_safe_geometry_fallback(self):
        class BrokenMeasurer:
            def measure(self, text, style, max_width):
                raise RuntimeError('metric failure')

        plan = plan_generated_layout(
            'dialogue',
            self.transcription_style,
            None,
            self.romanization_style,
            [],
            640,
            360,
            measurer=BrokenMeasurer(),
        )
        self.assertGreater(plan.transcription_box.height, 0)
        self.assertLessEqual(plan.transcription_box.bottom, 360)

    def test_positioned_and_moving_events_produce_obstacle_boxes(self):
        positioned = LayoutEvent(
            0, 1000, r'{\an8\pos(320,40)}Title', self.transcription_style,
            EventRole.OVERLAY,
        )
        moving = LayoutEvent(
            0, 1000, r'{\move(20,20,620,20)}Banner', self.transcription_style,
            EventRole.OVERLAY,
        )
        positioned_box = estimate_event_box(positioned, 640, 360)
        moving_box = estimate_event_box(moving, 640, 360)
        self.assertLess(positioned_box.top, 60)
        self.assertGreater(moving_box.width, 500)

    def test_lane_planner_avoids_obstacles_and_keeps_generated_tracks_in_bounds(self):
        obstacle = Rect(0, 280, 640, 360)
        plan = plan_generated_layout(
            'transcribed dialogue that wraps onto another line ' * 2,
            self.transcription_style,
            'romanized dialogue',
            self.romanization_style,
            [obstacle],
            640,
            360,
        )
        boxes = [plan.transcription_box, plan.romanization_box]
        for box in boxes:
            self.assertGreaterEqual(box.left, 0)
            self.assertGreaterEqual(box.top, 0)
            self.assertLessEqual(box.right, 640)
            self.assertLessEqual(box.bottom, 360)
            self.assertEqual(box.intersection_area(obstacle), 0)
        self.assertEqual(
            plan.transcription_box.intersection_area(plan.romanization_box), 0
        )
        repeated = plan_generated_layout(
            'transcribed dialogue that wraps onto another line ' * 2,
            self.transcription_style,
            'romanized dialogue',
            self.romanization_style,
            [obstacle],
            640,
            360,
        )
        self.assertEqual(plan, repeated)

    def test_generated_stack_avoids_dialogue_and_positioned_overlay_together(self):
        events = [
            LayoutEvent(
                0,
                1000,
                'bottom dialogue',
                self.transcription_style,
                EventRole.DIALOGUE,
            ),
            LayoutEvent(
                0,
                1000,
                r'{\an8\pos(320,130)}positioned overlay',
                self.transcription_style,
                EventRole.OVERLAY,
            ),
        ]
        obstacle_index = ObstacleIndex(events, 640, 360)
        obstacles = obstacle_index.query(100, 900)
        plan = plan_generated_layout(
            'generated dialogue',
            self.transcription_style,
            'romanized dialogue',
            self.romanization_style,
            obstacles,
            640,
            360,
        )
        for generated_box in (
            plan.transcription_box,
            plan.romanization_box,
        ):
            for obstacle in obstacles:
                self.assertEqual(
                    generated_box.intersection_area(obstacle), 0
                )

    def test_screenshot_like_three_track_stack_is_compact(self):
        base_style = self.transcription_style.copy()
        base_style.fontsize = 22
        obstacle = estimate_event_box(
            LayoutEvent(
                0,
                1000,
                r'base one\Nbase two',
                base_style,
                EventRole.DIALOGUE,
            ),
            640,
            360,
            FallbackTextMeasurer(),
        )
        plan = plan_generated_layout(
            'spoken',
            self.transcription_style,
            'romanized',
            self.romanization_style,
            [obstacle],
            640,
            360,
        )

        stack_height = obstacle.top - plan.romanization_box.top
        self.assertLessEqual(stack_height, 42)
        self.assertEqual(
            plan.transcription_box.intersection_area(obstacle), 0
        )
        self.assertEqual(
            plan.romanization_box.intersection_area(obstacle), 0
        )

    def test_obstacle_index_returns_only_active_events(self):
        events = [
            LayoutEvent(0, 1000, 'first', self.transcription_style, EventRole.DIALOGUE),
            LayoutEvent(2000, 3000, 'second', self.transcription_style, EventRole.DIALOGUE),
        ]
        index = ObstacleIndex(events, 640, 360)
        self.assertEqual(len(index.query(500, 600)), 1)
        self.assertEqual(len(index.query(1200, 1800)), 0)

    def test_explicit_source_lines_reserve_increasing_height(self):
        texts = [
            '',
            'one',
            r'one\Ntwo',
            r'one\Ntwo\Nthree\Nfour',
        ]
        boxes = [
            estimate_event_box(
                LayoutEvent(0, 1000, text, self.transcription_style, EventRole.DIALOGUE),
                640,
                360,
                FallbackTextMeasurer(),
            )
            for text in texts
        ]
        self.assertEqual(boxes[0].height, boxes[1].height)
        self.assertGreater(boxes[2].height, boxes[1].height)
        self.assertGreater(boxes[3].height, boxes[2].height)

    def test_layout_stays_in_bounds_across_script_resolutions_and_zones(self):
        for width, height in ((384, 288), (640, 360), (1920, 1080)):
            for zone in ('bottom', 'top'):
                with self.subTest(width=width, height=height, zone=zone):
                    plan = plan_generated_layout(
                        'dialogue ' * 15,
                        self.transcription_style,
                        'romanized ' * 12,
                        self.romanization_style,
                        [],
                        width,
                        height,
                        preferred_zone=zone,
                        measurer=FallbackTextMeasurer(),
                    )
                    for box in (plan.transcription_box, plan.romanization_box):
                        self.assertGreaterEqual(box.left, 0)
                        self.assertGreaterEqual(box.top, 0)
                        self.assertLessEqual(box.right, width)
                        self.assertLessEqual(box.bottom, height)

    def test_default_layout_measurement_is_host_independent(self):
        expected = plan_generated_layout(
            'deterministic dialogue',
            self.transcription_style,
            'romanized dialogue',
            self.romanization_style,
            [],
            640,
            360,
            measurer=FallbackTextMeasurer(),
        )
        with patch.object(
            FontAwareTextMeasurer,
            'measure',
            return_value=TextExtent(600, 200, 8),
        ):
            actual = plan_generated_layout(
                'deterministic dialogue',
                self.transcription_style,
                'romanized dialogue',
                self.romanization_style,
                [],
                640,
                360,
            )
        self.assertEqual(actual, expected)

    def test_generated_stack_matrix_is_compact_clear_and_in_bounds(self):
        base_texts = ('base', r'base one\Nbase two')
        transcription_texts = ('spoken', r'spoken one\Nspoken two')
        romanization_texts = (None, 'romanized', r'roman one\Nroman two')
        for width, height in ((384, 288), (640, 360), (1920, 1080)):
            for zone in ('bottom', 'top'):
                for base_text in base_texts:
                    obstacle_style = self.transcription_style.copy()
                    obstacle_style.alignment = 8 if zone == 'top' else 2
                    obstacle = estimate_event_box(
                        LayoutEvent(
                            0,
                            1000,
                            base_text,
                            obstacle_style,
                            EventRole.DIALOGUE,
                        ),
                        width,
                        height,
                        FallbackTextMeasurer(),
                    )
                    preferred = 'bottom' if zone == 'top' else 'top'
                    for transcription_text in transcription_texts:
                        for romanization_text in romanization_texts:
                            with self.subTest(
                                width=width,
                                height=height,
                                zone=zone,
                                base=base_text,
                                transcription=transcription_text,
                                romanization=romanization_text,
                            ):
                                plan = plan_generated_layout(
                                    transcription_text,
                                    self.transcription_style,
                                    romanization_text,
                                    self.romanization_style,
                                    [obstacle],
                                    width,
                                    height,
                                    preferred_zone=preferred,
                                )
                                boxes = [plan.transcription_box]
                                if plan.romanization_box:
                                    boxes.append(plan.romanization_box)
                                    gap = (
                                        plan.transcription_box.top
                                        - plan.romanization_box.bottom
                                    )
                                    self.assertAlmostEqual(gap, 0)
                                for box in boxes:
                                    self.assertGreaterEqual(box.left, 0)
                                    self.assertGreaterEqual(box.top, 0)
                                    self.assertLessEqual(box.right, width)
                                    self.assertLessEqual(box.bottom, height)
                                    self.assertEqual(
                                        box.intersection_area(obstacle), 0
                                    )


if __name__ == '__main__':
    unittest.main()
