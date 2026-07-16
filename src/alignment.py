from bisect import bisect_left
from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class WordTiming:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class AlignmentEvent:
    start: int
    end: int
    index: int
    text: str = ""
    style: str = ""
    alignment: int = 2
    positioned: bool = False
    words: tuple = field(default_factory=tuple)

    @property
    def duration(self):
        return max(1, self.end - self.start)

    @property
    def midpoint(self):
        return (self.start + self.end) / 2


@dataclass(frozen=True)
class TimeTransform:
    scale: float = 1.0
    offset: float = 0.0

    def apply(self, timestamp):
        return self.scale * timestamp + self.offset


@dataclass(frozen=True)
class Candidate:
    secondary: int
    base: int
    score: float
    overlap: int


@dataclass(frozen=True)
class EventMatch:
    secondary: int
    bases: tuple
    primary: int
    confidence: float
    transform: TimeTransform


def dialogue_anchor_confidence(event):
    """Estimate whether a base event represents spoken dialogue."""
    if not event.text.strip() or event.positioned:
        return 0.0
    style = event.style.lower().replace("-", "_").replace(" ", "_")
    overlay_markers = (
        "sign", "title", "eyecatch", "onscreen", "logo", "caption",
        "episode", "preview",
    )
    if any(marker in style for marker in overlay_markers):
        return 0.1
    dialogue_markers = (
        "main", "dialogue", "default", "flashback", "narration",
        "italics", "transcription", "secondary",
    )
    if any(marker in style for marker in dialogue_markers):
        return 0.8 if event.alignment in (7, 8, 9) else 1.0
    if event.alignment in (7, 8, 9):
        return 0.15
    if event.duration < 250:
        return 0.35
    return 1.0


def _nearest_index(sorted_values, value):
    position = bisect_left(sorted_values, value)
    options = []
    if position < len(sorted_values):
        options.append(position)
    if position:
        options.append(position - 1)
    return min(options, key=lambda idx: abs(sorted_values[idx] - value)) if options else None


def estimate_time_transform(base_events, secondary_events):
    anchors = [event for event in base_events if dialogue_anchor_confidence(event) >= 0.5]
    if not anchors or not secondary_events:
        return TimeTransform()

    anchors.sort(key=lambda event: event.midpoint)
    ordered_secondary = sorted(secondary_events, key=lambda event: event.midpoint)
    centers = [event.midpoint for event in anchors]
    sample_count = min(21, len(anchors), len(ordered_secondary))
    if sample_count < 4:
        return TimeTransform()
    quantile_offsets = []
    for sample in range(sample_count):
        fraction = sample / (sample_count - 1)
        base_index = round(fraction * (len(anchors) - 1))
        secondary_index = round(fraction * (len(ordered_secondary) - 1))
        quantile_offsets.append(
            anchors[base_index].midpoint - ordered_secondary[secondary_index].midpoint
        )
    coarse_offset = median(quantile_offsets)

    residuals = []
    for event in ordered_secondary:
        corrected = event.midpoint + coarse_offset
        nearest = _nearest_index(centers, corrected)
        if nearest is not None:
            residual = centers[nearest] - corrected
            if abs(residual) <= 2500:
                residuals.append(residual)
    if len(residuals) < 4:
        return TimeTransform(offset=coarse_offset)

    initial_offset = coarse_offset + median(residuals)
    pairs = []
    for event in ordered_secondary:
        corrected = event.midpoint + initial_offset
        nearest = _nearest_index(centers, corrected)
        if nearest is not None and abs(centers[nearest] - corrected) <= 1500:
            pairs.append((event.midpoint, centers[nearest]))

    if len(pairs) < 8 or pairs[-1][0] - pairs[0][0] < 60000:
        return TimeTransform(offset=initial_offset)

    mean_x = sum(pair[0] for pair in pairs) / len(pairs)
    mean_y = sum(pair[1] for pair in pairs) / len(pairs)
    denominator = sum((x - mean_x) ** 2 for x, _ in pairs)
    if not denominator:
        return TimeTransform(offset=initial_offset)
    scale = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / denominator
    scale = max(0.98, min(1.02, scale))
    offset = median(y - scale * x for x, y in pairs)
    return TimeTransform(scale=scale, offset=offset)


def _candidate_score(base, secondary, transform, tolerance):
    start = transform.apply(secondary.start)
    end = transform.apply(secondary.end)
    overlap = max(0, min(end, base.end) - max(start, base.start))
    boundary_gap = min(abs(start - base.end), abs(end - base.start))
    if overlap <= 0 and boundary_gap > tolerance:
        return None

    overlap_ratio = overlap / min(max(1, end - start), base.duration)
    boundary_error = abs(start - base.start) + abs(end - base.end)
    boundary_score = 1 - min(1, boundary_error / (base.duration + max(1, end - start)))
    midpoint_error = abs(((start + end) / 2) - base.midpoint)
    midpoint_score = 1 - min(1, midpoint_error / (max(base.duration, end - start) + tolerance))
    anchor_score = dialogue_anchor_confidence(base)
    score = 0.5 * overlap_ratio + 0.25 * boundary_score + 0.2 * midpoint_score + 0.05 * anchor_score
    if overlap <= 0:
        score *= 0.5
    return max(0.0, min(1.0, score)), round(overlap)


def discover_candidates(base_events, secondary_events, transform, tolerance=200):
    """Find temporal candidates with a sweep-line active set."""
    ordered_bases = sorted(enumerate(base_events), key=lambda item: item[1].start)
    ordered_secondary = sorted(enumerate(secondary_events), key=lambda item: item[1].start)
    candidates = []
    active = []
    base_cursor = 0

    for secondary_position, secondary in ordered_secondary:
        start = transform.apply(secondary.start)
        end = transform.apply(secondary.end)
        while base_cursor < len(ordered_bases) and ordered_bases[base_cursor][1].start <= end + tolerance:
            base_position, base = ordered_bases[base_cursor]
            if dialogue_anchor_confidence(base) > 0:
                active.append((base_position, base))
            base_cursor += 1
        active = [item for item in active if item[1].end >= start - tolerance]
        for base_position, base in active:
            scored = _candidate_score(base, secondary, transform, tolerance)
            if scored and scored[0] >= 0.12:
                candidates.append(Candidate(
                    secondary=secondary_position,
                    base=base_position,
                    score=scored[0],
                    overlap=scored[1],
                ))
    return candidates


class _PrefixMaximum:
    def __init__(self, size):
        self.values = [(0.0, None)] * (size + 1)

    def update(self, position, value):
        position += 1
        while position < len(self.values):
            if value[0] > self.values[position][0]:
                self.values[position] = value
            position += position & -position

    def query(self, position):
        position += 1
        result = (0.0, None)
        while position:
            if self.values[position][0] > result[0]:
                result = self.values[position]
            position -= position & -position
        return result


def select_monotonic_matches(base_events, secondary_events, candidates, transform):
    """Select a maximum-scoring monotonic chain, then expand contiguous overlaps."""
    if not base_events or not secondary_events or not candidates:
        return {}

    by_secondary = {}
    for candidate in candidates:
        by_secondary.setdefault(candidate.secondary, []).append(candidate)

    prefix = _PrefixMaximum(len(base_events))
    nodes = []
    for secondary in sorted(by_secondary):
        pending = []
        for candidate in sorted(by_secondary[secondary], key=lambda item: item.base):
            previous_score, previous_node = prefix.query(candidate.base)
            node_index = len(nodes)
            nodes.append((candidate, previous_node, previous_score + candidate.score))
            pending.append((candidate.base, (previous_score + candidate.score, node_index)))
        for base, value in pending:
            prefix.update(base, value)

    _, node_index = prefix.query(max(0, len(base_events) - 1))
    primary = {}
    while node_index is not None:
        candidate, previous_node, _ = nodes[node_index]
        primary[candidate.secondary] = candidate
        node_index = previous_node

    matches = {}
    for secondary_position, chosen in primary.items():
        related = by_secondary.get(secondary_position, [])
        threshold = max(0.25, chosen.score * 0.65)
        bases = {chosen.base}
        for candidate in related:
            if candidate.overlap > 0 and candidate.score >= threshold:
                bases.add(candidate.base)
        contiguous = sorted(bases)
        confidence_scores = [
            candidate.score for candidate in related if candidate.base in contiguous
        ]
        matches[secondary_position] = EventMatch(
            secondary=secondary_position,
            bases=tuple(contiguous),
            primary=chosen.base,
            confidence=sum(confidence_scores) / len(confidence_scores),
            transform=transform,
        )
    return matches


def align_events(base_events, secondary_events, tolerance=200):
    if not base_events or not secondary_events:
        return {}

    proposed = estimate_time_transform(base_events, secondary_events)
    identity = TimeTransform()
    identity_candidates = discover_candidates(
        base_events, secondary_events, identity, tolerance
    )
    if proposed == identity:
        transform = identity
        candidates = identity_candidates
    else:
        proposed_candidates = discover_candidates(
            base_events, secondary_events, proposed, tolerance
        )
        identity_coverage, identity_score = _candidate_evidence(identity_candidates)
        proposed_coverage, proposed_score = _candidate_evidence(proposed_candidates)
        improves_alignment = (
            proposed_coverage >= identity_coverage
            and proposed_coverage >= 4
            and proposed_score > identity_score * 1.1
        )
        if improves_alignment:
            transform = proposed
            candidates = proposed_candidates
        else:
            transform = identity
            candidates = identity_candidates
    return select_monotonic_matches(base_events, secondary_events, candidates, transform)


def _candidate_evidence(candidates):
    best_by_secondary = {}
    for candidate in candidates:
        best_by_secondary[candidate.secondary] = max(
            candidate.score,
            best_by_secondary.get(candidate.secondary, 0.0),
        )
    return len(best_by_secondary), sum(best_by_secondary.values())


def snap_times(secondary, match, base_events, tolerance=200, minimum_duration=100):
    if not match or match.confidence < 0.5:
        return secondary.start, secondary.end
    mapped = [base_events[position] for position in match.bases]
    target_start = min(event.start for event in mapped)
    target_end = max(event.end for event in mapped)
    corrected_start = match.transform.apply(secondary.start)
    corrected_end = match.transform.apply(secondary.end)
    start = target_start if abs(corrected_start - target_start) <= tolerance else secondary.start
    end = target_end if abs(corrected_end - target_end) <= tolerance else secondary.end
    if end - start < minimum_duration:
        return secondary.start, secondary.end
    return round(start), round(end)


def split_words_across_bases(words, match, base_events):
    """Assign timestamped words to mapped base cues without duplicating text."""
    if not words or not match or len(match.bases) < 2:
        return []
    groups = {base: [] for base in match.bases}
    for word in words:
        midpoint = match.transform.apply((word.start + word.end) / 2)
        containing = [
            base for base in match.bases
            if base_events[base].start <= midpoint < base_events[base].end
        ]
        if containing:
            selected = containing[0]
        else:
            selected = min(
                match.bases,
                key=lambda base: abs(base_events[base].midpoint - midpoint),
            )
        groups[selected].append(word)
    return [(base, tuple(groups[base])) for base in match.bases if groups[base]]
