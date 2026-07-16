# WhisperSub Contributor Guide

## Project scope

WhisperSub is a Python CLI that extracts MKV audio and subtitle tracks, transcribes speech through stable-ts and Faster-Whisper, aligns subtitle tracks, and renders merged ASS/SRT output. Preserve existing CLI workflows unless a task explicitly changes them.

## Architecture

- `whispersub.py` parses CLI arguments and orchestrates processing.
- `src/audio.py` owns ffmpeg extraction and optional Demucs vocal separation.
- `src/transcription.py` owns stable-ts/Faster-Whisper loading, sequential inference, fallback, and structured transcription results.
- `src/alignment.py` contains pure timing, candidate-discovery, monotonic matching, and snapping logic.
- `src/subtitles.py` owns subtitle parsing, normalization, styling, romanization integration, and output rendering.
- `src/cache.py` owns artifact manifests and atomic output helpers.
- `src/config.py` contains serializable processing configuration.
- `src/model_registry.py` lists advertised Whisper models. Compatible custom Faster-Whisper identifiers and paths must remain accepted.
- `src/utils.py` contains lightweight shared helpers and lazy device detection.

## Invariants

- Extract recognition audio and Demucs stems as 16 kHz mono PCM.
- Keep ML imports lazy so merge-only operations do not initialize or require the speech-recognition stack.
- Cache only artifacts with matching manifests. Include every setting that can change an artifact's contents.
- Write generated artifacts atomically; incomplete subprocess output must never become a valid cache entry.
- Use milliseconds internally for subtitle timing. Stable-ts JSON word timestamps are converted from seconds at the subtitle boundary.
- Preserve source signs, titles, and positioned overlays, but do not normally use them as dialogue alignment anchors.
- Maintain monotonic alignment and positive cue duration. Low-confidence timing should remain unsnapped.
- Preserve an explicitly selected Whisper model when retrying on CPU.
- Do not pass `batch_size` to Stable-ts transcription. It selects Faster-Whisper's VAD-driven batched pipeline, which can omit speech in this workload.

## Dependencies and commands

Runtime Python dependencies are in `requirements.txt`. External tools are `ffmpeg`, `mkvextract`, and `mkvinfo`; only require the tools needed by the selected CLI mode.

Run tests:

```bash
python -m unittest discover -s tests -v
```

Run the alignment benchmark:

```bash
python scripts/benchmark_alignment.py --events 10000
```

Check Python syntax without importing optional ML dependencies:

```bash
python -m compileall -q whispersub.py src tests scripts
```

## Change guidance

- Add focused regression tests for cache invalidation, alignment edge cases, and transcription fallback behavior.
- Benchmark alignment changes on long synthetic tracks; avoid reintroducing all-pairs cue matching.
- Keep rendering changes separate from inference so cached structured transcription can be reused.
- Update README usage and processing documentation when CLI behavior, cache keys, supported models, or external dependencies change.
- Do not commit generated subtitles, extracted media, model weights, or `.tmp` cache contents.
