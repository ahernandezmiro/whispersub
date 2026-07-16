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
from .model_registry import validate_model_name
from .utils import get_optimal_device_and_model, write_file


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
        result_json_path=None,
    ):
    """Transcribe audio through Stable-ts and Faster-Whisper."""
    import stable_whisper

    device, auto_model_name = get_optimal_device_and_model(force_cpu=force_cpu)
    resolved_model = validate_model_name(model_name or auto_model_name)
    compute_type = "float16" if device == "cuda" else "int8"
    result_json_path = result_json_path or _result_json_path(recognized_srt_path)

    config = TranscriptionConfig(
        model_name=resolved_model,
        device=device,
        compute_type=compute_type,
        voice_separation=voice_separation,
    )
    cache_config = config.as_cache_dict()
    cache_config.update({
        "backend": "faster-whisper",
        "stable_ts_version": _package_version("stable-ts-whisperless"),
        "faster_whisper_version": _package_version("faster-whisper"),
        "inference_mode": "sequential",
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

        print("[INFO] Running sequential transcription with language detection...")
        result = model.transcribe(**transcribe_args)

        result.split_by_length(max_words=15)
        _render_result(result, result_json_path, recognized_srt_path)
        detected_lang = result.language
        write_file(lang_cache_path, detected_lang)
        manifest["metadata"] = {"language": detected_lang}
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
                result_json_path=result_json_path,
            )
        raise
