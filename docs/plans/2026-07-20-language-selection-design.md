# Language Selection Design

## Goal

Prevent a weak language guess from an opening song or other unrepresentative
audio from forcing the wrong tokenizer for an entire transcription.

## Selection order

1. An explicit `--language` Whisper language code wins and skips automatic
   detection.
2. Without an override, decode the actual transcription input and inspect
   three 30-second windows distributed across its duration.
3. Read the selected MKV audio stream's language tag with `ffprobe`. Normalize
   ISO 639-2 container tags such as `jpn` to Whisper codes such as `ja`.
4. If the normalized tag's mean probability across the three windows is at
   least 0.60, select the tagged language.
5. Otherwise, sum each candidate language's probabilities across all windows
   and select the confidence-weighted winner.

Missing, unsupported, or unreadable metadata is non-fatal and falls back to
the distributed vote. Short recordings use as many distinct windows as their
duration allows.

## Pipeline and cache behavior

The selected language code is passed explicitly to Stable-ts/Faster-Whisper,
so its tokenizer cannot be determined by the first audio window. Detection is
performed on the Demucs vocal stem when voice separation is enabled, matching
the audio that will actually be transcribed.

The transcription manifest records the requested language, metadata hint,
detection strategy version, sample count, confidence threshold, selected
language, and selection source. These settings invalidate older cached
transcriptions, including results created by first-window-only detection.

## Verification

Regression tests cover explicit override precedence, metadata acceptance,
metadata rejection with weighted voting, ISO language normalization, and
cache invalidation. The existing transcription tests continue to ensure that
sequential inference, CPU fallback, and voice separation behave as before.
