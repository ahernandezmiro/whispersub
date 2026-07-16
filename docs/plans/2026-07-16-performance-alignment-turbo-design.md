# WhisperSub Performance, Alignment, and Turbo Design

## Objective

Improve WhisperSub's runtime efficiency, cache correctness, subtitle alignment accuracy, and Whisper model selection without removing or expanding its user-facing workflows. Existing CLI commands and output modes remain compatible.

## Delivery strategy

The work is staged so every phase can be tested independently:

1. Establish regression tests and typed internal configuration.
2. Replace basename-only caching and oversized audio intermediates.
3. Optimize transcription while preserving Stable-ts timestamp processing.
4. Replace independent subtitle snapping with monotonic many-to-many alignment.
5. Add Whisper Turbo and harden model fallback behavior.
6. Run multilingual regressions and update user documentation.

## Phase 1: foundation and cache architecture

### Internal configuration

Introduce dataclasses for audio extraction and transcription settings. These objects provide stable, serializable inputs for cache fingerprints and keep CLI parsing separate from execution.

### Artifact cache

Each cached artifact receives a JSON manifest containing:

- a schema version;
- canonical source path, size, and nanosecond modification time;
- track identifier;
- stage name and relevant configuration;
- backend/model identity where applicable.

An artifact is reusable only when both it and its manifest exist and the expected manifest matches. Writes use a sibling temporary path followed by an atomic replacement. Legacy files without manifests are treated as stale rather than trusted silently.

The transcription stage stores a Stable-ts JSON result as its canonical artifact. SRT is derived from JSON, allowing subtitle rendering and alignment changes without repeating inference.

### Module boundaries

Move ML imports into the transcription path so subtitle-only operations do not initialize PyTorch or Stable-ts. Keep orchestration in `whispersub.py`, with audio, transcription, matching, and rendering handled by focused modules and pure helpers where possible.

## Phase 2: extraction and transcription efficiency

### Audio extraction

Use ffmpeg to extract 16 kHz mono PCM instead of 44.1 kHz stereo PCM. Continue selecting the requested MKV stream. Write to a temporary WAV and rename it only after ffmpeg exits successfully.

### Accuracy-first Faster-Whisper inference

Use Stable-ts's Faster-Whisper integration for all ordinary transcription, including voice-separated transcription. Keep inference sequential: passing a batch size selects Faster-Whisper's VAD-driven batched pipeline, which can skip valid dialogue and is unsuitable for subtitle completeness. If CUDA inference fails, retry on CPU. Explicitly requested models remain unchanged during fallback.

### Voice separation

Keep separation as preprocessing rather than a reason to switch to vanilla Whisper. Demucs produces an independently cached vocal stem, which ffmpeg normalizes to 16 kHz mono before the Faster-Whisper backend consumes it. A GPU separation failure retries Demucs on CPU without changing the selected Whisper model. Separation settings participate in both the stem and transcription cache fingerprints.

## Phase 3: subtitle alignment

### Normalized events and anchor selection

Represent subtitle cues with timing, text, style, alignment/positioning metadata, source index, and optional word timing. Base cues remain in output unchanged. Likely signs, titles, and explicitly positioned overlays are excluded or penalized as dialogue timing anchors.

### Candidate discovery

Sort both tracks and use a sweep-line active set to discover temporal candidates in approximately `O(N + M + K)` time. Intervals are half-open, so cues that only touch at a boundary do not overlap.

### Global correction and sequence matching

Use high-confidence temporal anchors to estimate a robust global offset and, when enough anchors exist, small linear drift. Score local matches using overlap ratio, midpoint distance, boundary error, duration compatibility, and anchor confidence.

Select mappings with monotonic dynamic programming. The matcher supports unmatched cues, one-to-one, one-to-many, and many-to-one relationships without mapping later speech backward in the base track.

### Word-aware splitting and snapping

When structured word timing is available, split a transcription spanning multiple base cues only at word boundaries. Word-highlight events keep their original word timing and use the active dialogue cue for layout.

Snapping is confidence-based and must preserve positive duration, cue order, and non-crossing boundaries. Low-confidence transcription timing is left unchanged.

Related fixes include appending the currently discarded leading fragment, bounding identical-text aggregation by time gap, safe style fallback, and skipping blank cues without terminating the merge.

## Phase 4: Whisper Turbo

Add `turbo` to the advertised Whisper model names while preserving every existing model. A small model registry centralizes canonical names and rough memory classes. Custom model identifiers and filesystem paths supported by Faster-Whisper remain accepted.

Automatic model selection remains backward compatible in this iteration; Turbo is explicitly available through `--whisper-model turbo`. Benchmarks can justify a later default change.

GPU failure retries the same resolved model and options on CPU. Model, backend, compute type, inference mode, voice separation, and relevant inference settings are included in the cache manifest.

No Qwen or other ASR backend is introduced.

## Testing and acceptance criteria

### Unit tests

- Cache hit, miss, invalidation, basename collision, and incomplete artifact cases.
- Audio ffmpeg command construction and atomic replacement.
- Model validation, Turbo selection, device policy, and fallback preservation.
- Sweep-line candidates, dialogue anchor classification, offset/drift estimation, monotonic matching, many-to-many cases, word splitting, and constrained snapping.
- Regression tests for blank cues, aggregation gaps, missing styles, and leading fragments.

### Integration checks

- Existing CLI argument forms remain valid.
- Representative output retains all source text and valid timestamps.
- Merge-only imports do not require the ML stack.
- A changed model or preprocessing option invalidates transcription but not unrelated extraction artifacts.
- Sequential inference retains dialogue coverage on representative subtitle workloads.
- Merge runtime grows approximately linearly on synthetic long subtitle tracks.

## Out of scope

- New ASR backends or cloud services.
- Speaker diarization or translation features.
- Changes to supported romanization languages.
- User-facing cache management beyond the existing clear-cache operation.
