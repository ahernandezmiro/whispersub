from collections import defaultdict
from dataclasses import dataclass
import os
import platform
from importlib import metadata

from .audio import separate_vocals
from .cache import (
    atomic_output_path,
    build_manifest,
    cache_is_valid,
    read_manifest,
    write_manifest,
)
from .config import TranscriptionConfig
from .languages import (
    normalize_language as _normalize_language,
    supported_language_codes,
)
from .model_registry import validate_model_name
from .utils import get_optimal_device_and_model, write_file


_LANGUAGE_DETECTION_SAMPLES = 3
_LANGUAGE_DETECTION_STRATEGY = "distributed-confidence-v1"
_METADATA_CONFIDENCE_THRESHOLD = 0.60
_DISTRIBUTED_SAMPLE_POSITIONS = (0.15, 0.50, 0.85)


@dataclass(frozen=True)
class LanguageSelection:
    language: str
    source: str
    confidence: float


def _decode_audio(audio_path):
    from faster_whisper.audio import decode_audio
    return decode_audio(audio_path)


def _distributed_sample_starts(audio_length, sample_length):
    if audio_length <= 0:
        raise RuntimeError("Cannot detect language from empty audio")
    maximum_start = max(0, audio_length - sample_length)
    starts = [
        round(maximum_start * position)
        for position in _DISTRIBUTED_SAMPLE_POSITIONS
    ]
    return tuple(dict.fromkeys(starts))


def _select_language(
        model,
        audio_path,
        requested_language=None,
        metadata_language=None,
        metadata_confidence_threshold=_METADATA_CONFIDENCE_THRESHOLD,
    ):
    """Select one language from an override or distributed model evidence."""
    requested_code = _normalize_language(requested_language)
    if requested_language and not requested_code:
        supported = ", ".join(supported_language_codes())
        raise ValueError(
            f"Unsupported transcription language '{requested_language}'. "
            f"Use a Whisper language code: {supported}"
        )
    if requested_code:
        return LanguageSelection(requested_code, "override", 1.0)

    audio = _decode_audio(audio_path)
    sample_length = getattr(model.feature_extractor, "n_samples", 30 * 16000)
    sample_starts = _distributed_sample_starts(len(audio), sample_length)
    probability_totals = defaultdict(float)

    for sample_number, start in enumerate(sample_starts, 1):
        sample = audio[start:start + sample_length]
        top_language, top_probability, candidates = model.detect_language(
            audio=sample
        )
        print(
            f"[INFO] Language sample {sample_number}/{len(sample_starts)}: "
            f"{top_language} ({top_probability:.1%})"
        )
        if not candidates:
            candidates = [(top_language, top_probability)]
        for candidate, probability in candidates:
            candidate_code = _normalize_language(candidate)
            if candidate_code:
                probability_totals[candidate_code] += probability

    sample_count = len(sample_starts)
    metadata_code = _normalize_language(metadata_language)
    if metadata_language and not metadata_code:
        print(
            f"[WARNING] Ignoring unsupported audio language metadata: "
            f"{metadata_language}"
        )
    if metadata_code:
        metadata_confidence = probability_totals[metadata_code] / sample_count
        if metadata_confidence >= metadata_confidence_threshold:
            return LanguageSelection(
                metadata_code,
                "metadata",
                metadata_confidence,
            )
        print(
            f"[WARNING] Audio metadata suggests {metadata_code}, but distributed "
            f"confidence is only {metadata_confidence:.1%}; using model vote."
        )

    if not probability_totals:
        raise RuntimeError("Language detection returned no supported candidates")
    language, total_probability = max(
        probability_totals.items(),
        key=lambda item: item[1],
    )
    return LanguageSelection(
        language,
        "weighted-vote",
        total_probability / sample_count,
    )


def _package_version(distribution):
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unknown"


def _is_cuda_failure(error):
    message = str(error).lower()
    markers = ("cuda", "cudnn", "cublas", "out of memory", "driver")
    return any(marker in message for marker in markers)


def _clear_cuda_cache():
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, RuntimeError):
        pass


def _result_json_path(recognized_srt_path):
    return f"{os.path.splitext(recognized_srt_path)[0]}.json"


def _render_result(result, result_json_path, recognized_srt_path):
    with atomic_output_path(result_json_path) as temporary_json:
        result.save_as_json(temporary_json)
    with atomic_output_path(recognized_srt_path) as temporary_srt:
        result.to_srt_vtt(temporary_srt)


def transcribe_with_whisper(
        audio_path,
        recognized_srt_path,
        lang_cache_path,
        model_name=None,
        voice_separation=False,
        force_cpu=False,
        language=None,
        metadata_language=None,
        result_json_path=None,
    ):
    """Transcribe audio through Stable-ts and Faster-Whisper."""
    import stable_whisper

    device, auto_model_name = get_optimal_device_and_model(force_cpu=force_cpu)
    requested_language = _normalize_language(language)
    if language and not requested_language:
        supported = ", ".join(supported_language_codes())
        raise ValueError(
            f"Unsupported transcription language '{language}'. "
            f"Use a Whisper language code: {supported}"
        )
    metadata_language_code = _normalize_language(metadata_language)

    resolved_model = validate_model_name(model_name or auto_model_name)
    compute_type = "float16" if device == "cuda" else "int8"
    result_json_path = result_json_path or _result_json_path(recognized_srt_path)

    config = TranscriptionConfig(
        model_name=resolved_model,
        device=device,
        compute_type=compute_type,
        requested_language=requested_language,
        metadata_language=metadata_language_code,
        voice_separation=voice_separation,
    )
    cache_config = config.as_cache_dict()
    cache_config.update({
        "backend": "faster-whisper",
        "stable_ts_version": _package_version("stable-ts-whisperless"),
        "faster_whisper_version": _package_version("faster-whisper"),
        "inference_mode": "sequential",
        "language_detection_strategy": _LANGUAGE_DETECTION_STRATEGY,
        "language_detection_samples": _LANGUAGE_DETECTION_SAMPLES,
        "metadata_confidence_threshold": _METADATA_CONFIDENCE_THRESHOLD,
        "max_words": 15,
        "voice_separation_model": "htdemucs" if voice_separation else None,
    })
    manifest = build_manifest("transcription", audio_path, cache_config)

    if cache_is_valid(result_json_path, manifest):
        current_manifest = read_manifest(result_json_path)
        detected_lang = current_manifest.get("metadata", {}).get("language")
        print(f"[INFO] Whisper transcription: '{result_json_path}' already exists.")
        result = stable_whisper.WhisperResult(result_json_path)
        if not os.path.isfile(recognized_srt_path):
            with atomic_output_path(recognized_srt_path) as temporary_srt:
                result.to_srt_vtt(temporary_srt)
        if detected_lang:
            write_file(lang_cache_path, detected_lang)
        return detected_lang or result.language, recognized_srt_path

    transcribe_args = {
        "audio": audio_path,
        "task": "transcribe",
        "vad": config.vad,
        "vad_threshold": config.vad_threshold,
        "word_timestamps": config.word_timestamps,
        "nonspeech_error": 0.1,
        "min_word_dur": 0.1,
        "condition_on_previous_text": config.condition_on_previous_text,
        "q_levels": 20,
        "temperature": config.temperature,
    }

    system = platform.system().lower()
    demucs_supported = system != "darwin"
    if voice_separation and not demucs_supported:
        print(f"[INFO] Demucs separation disabled on {system}/{device} due to compatibility issues")

    try:
        if voice_separation and demucs_supported:
            vocals_path = f"{os.path.splitext(audio_path)[0]}_vocals.wav"
            try:
                transcribe_args["audio"] = separate_vocals(
                    audio_path,
                    vocals_path,
                    device=device,
                )
            except Exception:
                if device != "cuda":
                    raise
                print("[WARNING] GPU voice separation failed; retrying Demucs on CPU.")
                transcribe_args["audio"] = separate_vocals(
                    audio_path,
                    vocals_path,
                    device="cpu",
                )

        print(f"[INFO] Loading faster-whisper model: {resolved_model} on {device}")
        model = stable_whisper.load_faster_whisper(
            resolved_model,
            compute_type=compute_type,
            device=device,
        )

        selection = _select_language(
            model,
            transcribe_args["audio"],
            requested_language=requested_language,
            metadata_language=metadata_language_code,
        )
        transcribe_args["language"] = selection.language
        print(
            f"[INFO] Selected transcription language: {selection.language} "
            f"({selection.source}, {selection.confidence:.1%})"
        )

        print("[INFO] Running sequential transcription...")
        result = model.transcribe(**transcribe_args)
        result.split_by_length(max_words=15)

        _render_result(result, result_json_path, recognized_srt_path)
        detected_lang = result.language
        write_file(lang_cache_path, detected_lang)
        manifest["metadata"] = {
            "language": detected_lang,
            "selected_language": selection.language,
            "language_source": selection.source,
            "language_confidence": selection.confidence,
        }
        write_manifest(result_json_path, manifest)
        return detected_lang, recognized_srt_path

    except Exception as error:
        print(f"[ERROR] Transcription failed on {device}: {error}")
        if device == "cuda" and _is_cuda_failure(error):
            print("[INFO] Hardware acceleration failed, falling back to CPU...")
            _clear_cuda_cache()
            return transcribe_with_whisper(
                audio_path,
                recognized_srt_path,
                lang_cache_path,
                model_name=resolved_model,
                voice_separation=voice_separation,
                force_cpu=True,
                language=language,
                metadata_language=metadata_language,
                result_json_path=result_json_path,
            )
        raise
