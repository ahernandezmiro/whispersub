import unittest

from src.alignment import (
    AlignmentEvent,
    SnapProposal,
    TimeTransform,
    WordTiming,
    align_events,
    dialogue_anchor_confidence,
    discover_candidates,
    estimate_time_transform,
    resolve_snapped_spans,
    split_words_across_bases,
)


class AlignmentTests(unittest.TestCase):
    def test_empty_base_track_has_no_matches(self):
        secondary = [AlignmentEvent(0, 1000, 0, text="spoken text")]
        self.assertEqual(align_events([], secondary), {})

    def test_titles_and_positioned_events_are_not_dialogue_anchors(self):
        title = AlignmentEvent(0, 1000, 0, text="Episode", style="Show_Title")
        positioned = AlignmentEvent(0, 1000, 1, text="Sign", positioned=True)
        dialogue = AlignmentEvent(0, 1000, 2, text="Hello", style="Main")
        top_dialogue = AlignmentEvent(0, 1000, 3, text="Hello", style="Main_Top", alignment=8)
        self.assertLess(dialogue_anchor_confidence(title), 0.5)
        self.assertEqual(dialogue_anchor_confidence(positioned), 0)
        self.assertEqual(dialogue_anchor_confidence(dialogue), 1)
        self.assertGreater(dialogue_anchor_confidence(top_dialogue), 0.5)

    def test_boundary_touch_is_not_an_overlap(self):
        base = [AlignmentEvent(0, 1000, 0, text="base")]
        secondary = [AlignmentEvent(1000, 2000, 0, text="secondary")]
        candidates = discover_candidates(base, secondary, TimeTransform(), tolerance=0)
        self.assertTrue(all(candidate.overlap == 0 for candidate in candidates))

    def test_matches_are_monotonic_and_expand_one_to_many(self):
        base = [
            AlignmentEvent(0, 1000, 0, text="one"),
            AlignmentEvent(1000, 2000, 1, text="two"),
            AlignmentEvent(2000, 3000, 2, text="three"),
        ]
        secondary = [
            AlignmentEvent(50, 1900, 0, text="one two"),
            AlignmentEvent(2050, 2950, 1, text="three"),
        ]
        matches = align_events(base, secondary, tolerance=200)
        self.assertEqual(matches[0].bases, (0, 1))
        self.assertEqual(matches[1].primary, 2)

    def test_estimates_a_systematic_track_offset(self):
        base = [
            AlignmentEvent(index * 2500 + 2000, index * 2500 + 3800, index, text=str(index))
            for index in range(20)
        ]
        secondary = [
            AlignmentEvent(index * 2500, index * 2500 + 1800, index, text=str(index))
            for index in range(20)
        ]
        transform = estimate_time_transform(base, secondary)
        self.assertAlmostEqual(transform.offset, 2000, delta=20)
        matches = align_events(base, secondary, tolerance=200)
        self.assertAlmostEqual(matches[0].transform.offset, 2000, delta=20)

    def test_rejects_offset_that_reduces_alignment_evidence(self):
        secondary = [
            AlignmentEvent(index * 2500, index * 2500 + 1800, index, text=str(index))
            for index in range(40)
        ]
        base = [
            AlignmentEvent(event.start, event.end, event.index, text=event.text)
            for event in secondary
        ]
        base.extend(
            AlignmentEvent(10000 + index * 500, 10400 + index * 500, 100 + index, text="extra")
            for index in range(30)
        )
        base.sort(key=lambda event: event.start)
        matches = align_events(base, secondary, tolerance=200)
        self.assertEqual(matches[0].transform, TimeTransform())

    def test_estimates_small_linear_drift(self):
        secondary = [
            AlignmentEvent(index * 5000, index * 5000 + 1800, index, text=str(index))
            for index in range(40)
        ]
        base = [
            AlignmentEvent(
                round(event.start * 1.001 + 500),
                round(event.end * 1.001 + 500),
                event.index,
                text=event.text,
            )
            for event in secondary
        ]
        transform = estimate_time_transform(base, secondary)
        self.assertAlmostEqual(transform.scale, 1.001, delta=0.0002)
        self.assertAlmostEqual(transform.offset, 500, delta=30)

    def test_words_are_split_without_duplication(self):
        base = [
            AlignmentEvent(0, 1000, 0, text="one"),
            AlignmentEvent(1000, 2000, 1, text="two"),
        ]
        secondary = [AlignmentEvent(0, 2000, 0, text="hello world")]
        match = align_events(base, secondary, tolerance=200)[0]
        words = (
            WordTiming(100, 500, " hello"),
            WordTiming(1200, 1600, " world"),
        )
        groups = split_words_across_bases(words, match, base)
        self.assertEqual([base_index for base_index, _ in groups], [0, 1])
        self.assertEqual("".join(word.text for _, group in groups for word in group).strip(), "hello world")

    def test_overlay_between_dialogue_cues_does_not_break_expansion(self):
        base = [
            AlignmentEvent(0, 1000, 0, text="one", style="Main"),
            AlignmentEvent(500, 1500, 1, text="sign", style="Sign_Basic", positioned=True),
            AlignmentEvent(1000, 2000, 2, text="two", style="Main"),
        ]
        secondary = [AlignmentEvent(0, 2000, 0, text="one two")]
        match = align_events(base, secondary, tolerance=200)[0]
        self.assertEqual(match.bases, (0, 2))

    def test_ordered_snap_resolver_rejects_only_conflicting_boundaries(self):
        spans = [(1000, 1100), (1100, 1200)]
        proposals = [
            SnapProposal(start=950, end=1250),
            SnapProposal(start=950, end=1250),
        ]
        self.assertEqual(
            resolve_snapped_spans(spans, proposals),
            [(950, 1100), (1100, 1250)],
        )

    def test_ordered_snap_resolver_preserves_existing_source_overlap(self):
        spans = [(1000, 1200), (1100, 1300)]
        self.assertEqual(
            resolve_snapped_spans(spans, [SnapProposal(), SnapProposal()]),
            spans,
        )

    def test_ordered_snap_resolver_keeps_every_span_positive(self):
        spans = [(1000, 1001), (1001, 1002)]
        proposals = [
            SnapProposal(end=1000),
            SnapProposal(start=1002),
        ]
        self.assertEqual(resolve_snapped_spans(spans, proposals), spans)


if __name__ == "__main__":
    unittest.main()
