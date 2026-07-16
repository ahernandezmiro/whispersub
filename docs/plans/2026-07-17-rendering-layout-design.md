# WhisperSub Dialogue Styling and Geometry-Aware Layout Plan

## Status

Planned. This document defines the next rendering iteration; it does not add or remove user-facing features.

## Objective

Make generated transcription and romanization subtitles visually predictable when dialogue overlaps titles, signs, opening credits, or other positioned ASS events. Preserve every source subtitle event and its original styling while improving how generated events choose styles and screen positions.

The implementation should address three related problems:

1. A timing match against a non-speech cue can currently make generated speech inherit that cue's style.
2. Romanization can inherit a base dialogue style's color and vertical placement instead of retaining the configured/default romanization appearance.
3. Vertical placement uses explicit line counts as a proxy for rendered height, which does not account for wrapping, font metrics, resolution, alignment, or explicit positioning tags.

## Current behavior and constraints

- Base subtitle events and their styles are preserved. The observed color and position changes affect dynamically generated transcription and romanization styles.
- The default `Romanized` style is grey (`BCBCBC`), but a dynamically cloned style can inherit the matched base style's primary color.
- Dynamic vertical margins are calculated from explicit `\\N` line counts. Long automatically wrapped lines and ASS override tags are not represented in that calculation.
- Titles and signs have low dialogue-anchor confidence, but can still enter the candidate set and donate their style or placement to generated speech.
- Semantic classification can never be perfect from subtitle metadata alone. The design must fail safely and deterministically when a cue's role is uncertain.

## Design decision

Separate three concerns that are currently coupled:

1. **Timing alignment** decides which events correspond in time.
2. **Style eligibility** decides whether a matched base event may influence generated speech styling.
3. **Layout planning** treats all active screen elements as geometry and chooses a collision-free lane for generated text.

A style-name blacklist alone would be simple but brittle across subtitle authors and languages. Always using the default generated styles would be stable, but would discard useful dialogue placement such as intentional top-aligned speech. The selected approach retains layout hints from high-confidence dialogue while treating titles, signs, credits, and positioned graphics as obstacles that cannot donate speech styles.

## Phase 1: classify event roles and split matching outputs

### Event role model

Extend normalized base events with an internal rendering role:

- `dialogue`: a high-confidence speech subtitle that may donate approved layout properties.
- `overlay`: a title, sign, credit, song graphic, or explicitly positioned visual cue. It occupies screen space but never donates generated speech styling.
- `unknown`: insufficient evidence. It participates in timing analysis only when useful, but follows the safe overlay styling policy.

Role classification should combine existing dialogue-anchor confidence with style-name markers, ASS alignment, drawing/positioning tags, and event metadata. Keep the classifier isolated and deterministic so that rules can evolve without modifying the alignment algorithm.

### Separate result types

Replace the implicit assumption that one match serves every purpose with distinct internal results:

- `timing_match`: correspondence used for snapping or text transfer.
- `layout_anchor`: optional high-confidence dialogue event allowed to influence generated placement.
- `active_obstacles`: every overlapping base event whose rendered region must be avoided.

Non-dialogue events must not become `layout_anchor` values. Empty tracks and unmatched events must continue to use safe defaults.

### Acceptance criteria

- A title/sign/credit event cannot cause generated speech to use its style, alignment, color, or explicit position.
- Timing alignment remains monotonic and retains its current accuracy on existing fixtures.
- Unknown roles resolve to the safe default rather than inheriting arbitrary base styling.

## Phase 2: make generated style policy explicit

### Preserve source styling

- Never mutate source styles or source events.
- Continue emitting every base event with its original style.
- Treat source style objects as read-only inputs to generated style construction.

### Construct generated styles from canonical defaults

Build transcription and romanization styles from their canonical defaults, then copy only approved layout properties from a high-confidence dialogue anchor. Do not clone arbitrary base styles wholesale.

Approved inherited properties should initially be limited to:

- top/bottom alignment zone;
- safe vertical margin or lane preference;
- optionally font-size constraints when required to fit the selected lane.

Properties that remain owned by the generated style include:

- primary/secondary colors;
- outline and shadow policy;
- font face and configured font size;
- user-provided transcription or romanization overrides.

Romanization must remain grey by default and use `--rom-color` when supplied, regardless of the matched base dialogue color. Transcription follows its own configured/default color in the same way.

Use deterministic style keys derived from the generated track type and layout plan rather than source style names. This prevents styles such as `Romanized_*_Show_Title` from appearing in output.

### Acceptance criteria

- Generated romanization is `BCBCBC` unless the user supplies a color override.
- Generated transcription and romanization never carry sign/title/credit style names.
- Existing CLI style controls remain authoritative.
- Repeated runs with identical inputs produce identical style definitions and assignments.

## Phase 3: replace line-count placement with geometry-aware layout

### Layout model

Introduce a pure internal layout stage that produces approximate screen-space boxes for active events. Its inputs include:

- script `PlayResX` and `PlayResY`;
- alignment and margins;
- font size, scale, spacing, outline, and shadow;
- explicit line breaks and estimated automatic wrapping;
- ASS override tags such as `\\an`, `\\pos`, and `\\move`;
- event start/end times and layer.

The model does not need to reproduce libass pixel-for-pixel. It needs a conservative, deterministic estimate that is materially safer than counting explicit lines.

### Text measurement

Use an injectable text measurer:

1. Prefer real font metrics when the selected font can be resolved locally.
2. Otherwise use a conservative width/height estimator based on font size, scale, character classes, and available line width.
3. Account for explicit `\\N` breaks before estimating automatic wrapping.

The fallback must never fail rendering because a font is unavailable.

### Lane selection and collision handling

- Represent source dialogue, overlays, transcription, and romanization as occupied rectangles over time.
- Treat `\\pos`/`\\move` events as obstacles even when their semantic role is uncertain.
- Prefer stable bottom and top lanes rather than shifting generated text for small frame-to-frame changes.
- Stack transcription and romanization with explicit padding and a fixed ordering.
- Avoid active source events, clamp boxes to a configurable internal safe area, and preserve readable margins.
- When no fully clear lane exists, choose the placement with the least overlap and retain the generated style's visual identity.
- Fall back to the current safe default alignment if geometry cannot be calculated.

Keep layout planning separate from ASS serialization. The planner should return a small, testable layout description; the renderer should only translate it into styles and override tags.

### Acceptance criteria

- Generated boxes stay within the script resolution's safe bounds.
- Transcription and romanization do not overlap one another in the supported fixture matrix.
- A simultaneous sign/title remains visible and does not change generated speech styling.
- Long automatically wrapped lines reserve more height than short single-line text.
- Placement is stable for adjacent word-level fragments belonging to the same utterance.

## Phase 4: validation and regression coverage

### Unit fixtures

Build a compact matrix covering:

- zero, one, two, and four explicit base lines;
- long lines that wrap without `\\N`;
- bottom, top, and alternate dialogue styles;
- show titles, signs, opening/ending credits, and next-episode cards;
- explicitly positioned and moving overlays;
- simultaneous dialogue plus overlay events;
- multiple overlapping translation events;
- romanization enabled and disabled;
- word-level fragments;
- several `PlayResX`/`PlayResY` combinations;
- missing-font fallback behavior.

Use minimal synthetic text and metadata based on the structural cases observed during testing. Do not add copyrighted media or dialogue to the repository.

### Assertions

Combine semantic assertions with small golden ASS snapshots:

- all source events and styles are preserved;
- generated events use an eligible style source;
- configured colors, alignment, and ordering are retained;
- estimated boxes do not overlap in cases with available space;
- events remain within screen bounds and retain positive durations;
- serialized output is deterministic;
- current alignment and transcription-only regressions remain covered.

Golden snapshots should be reserved for representative end-to-end cases; geometry and role decisions should primarily use focused assertions to avoid brittle tests.

### Optional visual verification

Add a developer-only fixture rendering command that invokes ffmpeg/libass when available and creates reference frames for manual comparison. This is verification tooling, not a runtime dependency or user-facing feature.

## Implementation sequence

1. Add event-role classification and tests without changing rendering output.
2. Split timing matches from layout anchors and obstacle collection.
3. Replace source-style cloning with canonical generated-style construction.
4. Add the geometry types and deterministic fallback text measurer.
5. Implement lane selection and connect it to generated event rendering.
6. Add the fixture matrix, semantic assertions, and selected golden snapshots.
7. Run the complete unit suite plus representative transcribe, merge, and full-pipeline samples.
8. Update README and AGENTS documentation with the internal behavior and troubleshooting notes.

Each step should be independently testable and should preserve the CLI and current feature set.

## Compatibility and migration

- No CLI flags are added or removed.
- Existing user-provided color, font, size, and romanization settings retain precedence.
- Cache invalidation is required only if cached files contain rendered ASS output or internal layout decisions; raw transcription caches remain reusable.
- Existing projects that relied on accidental inheritance from non-dialogue styles will instead receive the documented default generated styles.

## Risks and mitigations

- **Role misclassification:** default unknown cues to obstacle-only behavior and keep rules observable in tests.
- **Font differences across systems:** use conservative fallback metrics and test both resolved and unresolved fonts.
- **Layout jitter at word level:** plan placement per utterance/time cluster and reuse it for its fragments.
- **Dense screens with no clear lane:** minimize overlap deterministically, preserve generated colors, and never discard an event.
- **Performance regression:** cache text measurements and interval/obstacle queries; benchmark layout independently on long subtitle tracks.

## Definition of done

- No generated event inherits styling from a title, sign, credit, or positioned overlay.
- Default romanization remains grey unless explicitly overridden.
- Source events and styles are preserved semantically.
- The layout fixture matrix remains in bounds and avoids collisions whenever a valid lane exists.
- Long-line wrapping and word-level stability are covered by regression tests.
- Full tests, dependency checks, and representative pipeline runs pass on CPU and CUDA-capable configurations.
