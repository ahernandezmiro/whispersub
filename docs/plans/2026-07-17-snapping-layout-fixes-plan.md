# Subtitle Snapping and Layout Correctness Plan

## Status

Proposed. This plan addresses the confirmed duplicate-cue and excessive-spacing defects documented in `docs/TODO.md`. It does not change the CLI surface or the transcription model pipeline.

## Objectives

1. Prevent matching and snapping from introducing overlaps into an originally ordered transcription track.
2. Preserve exact internal word/highlight timings while still allowing utterance-level synchronization with a base subtitle track.
3. Remove phantom subtitle lines introduced while parsing CRLF SRT files.
4. Make serialized layout decisions deterministic across supported environments.
5. Keep generated transcription and romanization compact, readable, in bounds, and clear of active source obstacles.

## Confirmed root causes

### Independent word-fragment snapping

Word-level transcription bypasses aggregation and sends every highlight frame through alignment and `snap_times()` independently. Adjacent fragments can therefore snap their starts or ends to the same base boundary even though their source times do not overlap.

In the JJK diagnostic sample, the source contains 4,053 ordered layer-2 events with no overlaps. The merged output contains 65 newly introduced overlaps, including 56 overlaps with identical cleaned text. Around 02:18, two adjacent source fragments at `138260–138272` and `138272–138440` become `138130–138270` and `138130–138440`.

### CRLF parser artifacts

`try_load_subtitles()` decodes subtitle bytes and passes CRLF content directly to `pysubs2.SSAFile.from_string()`. With the pinned `pysubs2` version, the auto-detected SRT parser can retain carriage returns around cue separators and convert them into a trailing `\N`.

In the diagnostic transcription, 4,052 of 4,053 events acquire a phantom trailing line. Normalizing newlines before parsing removes all of them. For the 02:18 cue, normalization reduces the estimated transcription height from `37.82` to `20.41` script units and the romanization height from `21.43` to `12.22`; the generated romanization margin changes from `104` to `87`.

### Environment-dependent measurement

`FontAwareTextMeasurer` uses Pillow and locally resolved fonts when available, otherwise it falls back to the deterministic estimator. Pillow is optional and not declared as a runtime dependency, so installing it can currently change serialized margins for identical inputs.

Playback is also not pixel-identical across all clients. ASS positions are expressed in script-resolution coordinates and scale with the video, while font substitution, wrapping, aspect-ratio behavior, and renderer differences remain client-controlled.

## Design decisions

### Normalize at the parsing boundary

Normalize `CRLF` and lone `CR` to `LF` immediately after successful decoding and before passing content to `pysubs2`. Do not remove trailing `\N` tags after parsing: an explicit authored ASS line break must remain valid.

Content-based format detection must remain in place because an extracted ASS track may use an `.srt` working filename. The fix must therefore not select the parser solely from the extension.

### Align word-level utterances, not highlight frames

Introduce an internal render-group representation for word-level transcription. A group contains:

- the cleaned utterance text, excluding highlight tags;
- the original envelope start and end;
- the ordered source events that render the changing highlight state.

Consecutive non-empty events belong to one group when their cleaned text is identical and their timing gap is within the existing aggregation tolerance. Non-word-level transcription and secondary subtitle cues use one group per already-aggregated event.

Alignment and snapping operate on group envelopes. Internal member boundaries remain unchanged. If the envelope start or end is accepted, only the first member's start or the last member's end is extended or shortened. This preserves Whisper's word timings and avoids rescaling karaoke progression.

### Resolve snapped spans as an ordered sequence

Replace isolated final timing decisions with a sequence-level resolver:

1. Calculate proposed snapped boundaries using the existing confidence and tolerance rules.
2. Start from the original ordered spans.
3. Accept a proposed boundary only when it preserves positive duration and does not increase overlap with either neighboring source span.
4. Reject only the conflicting boundary snap; do not clamp a member to zero duration and do not discard its text.
5. Preserve source overlap when speakers genuinely overlap, but never introduce additional overlap.

The resolver belongs in `src/alignment.py` and remains independent of `pysubs2`. Word-level grouping and expansion back into rendered events belong in `src/subtitles.py`.

### Use deterministic runtime layout measurement

Use one deterministic text measurer for serialized layout decisions. Local font discovery and Pillow measurement may remain available for developer diagnostics, but optional packages or host fonts must not silently change generated ASS styles.

Continue treating all active source cues as obstacles. Retain the current top/bottom lane model and canonical generated styles. Model transcription and romanization as a compact generated stack with a single explicit inter-track gap. Conservative obstacle inflation must not also become extra spacing between generated language tracks.

First re-render the synthetic and JJK diagnostic cases after newline normalization. Tune the inter-track gap only if the corrected render still exceeds the compactness acceptance bounds; do not compensate for phantom lines by changing font-size or margin constants.

## Implementation sequence

### Phase 1: add failing regressions

Add focused tests before changing production behavior:

1. A CRLF SRT fixture loaded through `try_load_subtitles()` has the same event text as its LF equivalent and contains no parser-created trailing `\N`.
2. Explicit authored `\N` inside ASS text survives loading unchanged.
3. A synthetic word-level utterance using the 02:18 timing pattern remains ordered after merging against a base cue.
4. The number and text of highlight frames are preserved and every rendered duration remains positive.
5. An originally overlapping source pair retains its permitted overlap rather than being flattened.
6. A non-word-level adjacent pair cannot acquire overlap through snapping.

Use synthetic dialogue and timing values; do not commit the JJK media, subtitles, or screenshots.

### Phase 2: fix subtitle input normalization

In `src/subtitles.py`:

1. Add a small newline-normalization helper.
2. Apply it after decoding and before `SSAFile.from_string()`.
3. Keep the existing encoding fallback order and error reporting.
4. Confirm that ASS content stored under an `.srt` working name is still detected and parsed correctly.

Run the focused subtitle tests and inspect the generated event text before changing layout behavior.

### Phase 3: introduce grouped and monotonic snapping

In `src/subtitles.py`:

1. Group word-level highlight frames by cleaned utterance text and timing continuity.
2. Normalize one `AlignmentEvent` per group.
3. Align groups against the normalized base events.
4. Request proposed envelope snaps.

In `src/alignment.py`:

1. Separate snap proposal from final acceptance.
2. Add a pure ordered-span resolver enforcing positive duration and non-increasing overlap.
3. Return resolved group envelopes without importing rendering types.

Back in `src/subtitles.py`:

1. Apply accepted outer boundaries to the first and last group members.
2. Preserve all internal source boundaries and highlight formatting.
3. Calculate one layout plan and one generated style assignment per utterance group so adjacent highlight frames cannot jitter between lanes or margins.
4. Emit romanization with exactly the resolved member timings.

Apply the sequence resolver to non-word-level groups as well, so all snapping paths share the ordering invariant.

### Phase 4: make layout compact and deterministic

In `src/layout.py` and `src/subtitles.py`:

1. Route serialization through the deterministic measurer.
2. Keep font-aware measurement out of runtime decisions or expose it only to development verification code.
3. Represent transcription and optional romanization as one generated stack during lane selection.
4. Keep the inter-track gap separate from obstacle clearance.
5. Preserve configured font sizes, colors, margins, and top/bottom preference as authoritative inputs.
6. Retain deterministic least-overlap fallback when no clear lane exists.

Do not combine transcription and romanization into one ASS event. Separate events preserve layer behavior, style controls, and word-level highlighting while the shared layout plan keeps them together spatially.

### Phase 5: expand layout coverage

Add a synthetic matrix covering:

- one- and two-line base dialogue;
- one- and two-line transcription;
- romanization absent, one line, and two lines;
- top and bottom dialogue zones;
- explicit `\N` and estimated automatic wrapping;
- simultaneous dialogue and positioned overlays;
- multiple script resolutions;
- missing-font fallback.

Assertions must cover:

- generated boxes do not overlap one another;
- generated boxes stay within the script bounds;
- source obstacles are avoided when a clear lane exists;
- the gap between adjacent generated tracks stays within an explicit compactness bound;
- repeated planning produces identical style names, margins, and font sizes;
- adjacent word-level members reuse the same layout plan.

Add an optional developer-only ffmpeg/libass render fixture for visual comparison. It must not become a runtime dependency or a required unit test.

### Phase 6: documentation and full verification

Update README behavior notes to explain:

- snapping is utterance-based in word-level mode;
- internal word timestamps remain authoritative;
- runtime layout decisions are deterministic;
- ASS layout scales from `PlayResX`/`PlayResY`, while exact glyph rendering can still vary by player and installed fonts.

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q whispersub.py src tests scripts
python scripts/benchmark_alignment.py --events 10000
python scripts/benchmark_layout.py --events 10000
```

Regenerate the ignored JJK diagnostic output from the existing cached structured transcription and compare:

- layer-2 overlap count;
- same-text overlap count;
- generated style margins;
- visual spacing for representative one- and two-line base cues.

The diagnostic artifacts remain ignored and must not be committed.

## Acceptance criteria

- CRLF and LF versions of the same subtitle file produce equivalent parsed events.
- No parser-created trailing `\N` appears in generated transcription or romanization.
- Snapping introduces zero new overlaps into a source sequence that did not overlap.
- Word-level frame count, ordering, text, and internal timestamps are preserved, except for accepted outer utterance boundaries.
- Every generated event has positive duration.
- The 02:18 synthetic regression no longer duplicates the line.
- Transcription and romanization remain compact across the supported line-count matrix.
- Identical inputs and configuration produce identical generated styles and margins regardless of optional Pillow installation or local fonts.
- Source styles and events remain unchanged, including authored line breaks and positioned overlays.
- Existing CLI flags, cacheable structured transcription, and merge-only workflows remain compatible.

## Alternatives rejected

### Clamp every event against the previous end

This would conceal conflicting snap decisions, shorten or erase very small highlight frames, and fail to address why multiple fragments choose the same boundary.

### Disable snapping for all word-level output

This would prevent the bug but discard useful synchronization between the transcription utterance and the base dialogue track.

### Proportionally retime every word in a snapped utterance

This preserves relative ordering but changes Whisper's internal word timestamps. The selected design changes only the utterance's external boundaries.

### Require libass rendering during layout

Renderer-backed measurement could improve fidelity on one machine, but it would add a merge-time dependency, make output depend on local fonts and renderer versions, and still would not guarantee identical playback in other clients.

## Definition of done

The fix is complete when the new regressions pass, the full suite and benchmarks remain healthy, the ignored JJK diagnostic produces no newly introduced transcription overlaps, and corrected sample renders demonstrate compact one-line and multi-line stacking without sacrificing obstacle avoidance or deterministic fallback behavior.
