import stable_whisper
import platform
from .utils import file_exists, write_file, get_optimal_device_and_model

def transcribe_with_whisper(
        audio_path, 
        recognized_srt_path, 
        lang_cache_path,
        model_name=None,
        voice_separation=False,
        force_cpu=False
    ):
    """
    Cross-platform Whisper transcription with automatic device optimization
    """
    if file_exists(recognized_srt_path):
        print(f"[INFO] Whisper transcription: '{recognized_srt_path}' already exists.")
        if file_exists(lang_cache_path):
            with open(lang_cache_path, 'r') as f:
                detected_lang = f.read().strip()
            print(f"[INFO] Using cached language detection: {detected_lang}")
            return detected_lang, recognized_srt_path

    device, auto_model_name = get_optimal_device_and_model(force_cpu=force_cpu)
    if model_name is None:
        model_name = auto_model_name
    
    transcribe_args = {
        "audio": audio_path,
        "task": "transcribe",
        "vad": True,   
        "vad_threshold": 0.35, 
        "word_timestamps": True,
        "nonspeech_error": 0.1,
        "min_word_dur": 0.1,       
        "condition_on_previous_text": True,
        "q_levels": 20,
        "temperature": 0.0,
    }
    
    system = platform.system().lower()
    demucs_supported = device in ["cuda", "cpu"] and system != "darwin"
    
    if voice_separation:
        if demucs_supported:
            transcribe_args.update({
                "denoiser": "demucs",
                "denoiser_options": {
                    "model": "htdemucs",
                    "device": device,
                }
            })
        else:
            print(f"[INFO] Demucs separation disabled on {system}/{device} due to compatibility issues")

    try:
        if not voice_separation:
            print(f"[INFO] Loading faster-whisper model: {model_name} on {device}")
            model = stable_whisper.load_faster_whisper(
                model_name, 
                compute_type=("float16" if device == "cuda" else "int8"), 
                device=device,
            )
        else:
            print(f"[INFO] Loading standard whisper model: {model_name} on {device}")
            model = stable_whisper.load_model(model_name, device=device)
            transcribe_args["suppress_ts_tokens"] = False

        print(f"[INFO] Running transcription with language detection...")
        
        transcribed_result = model.transcribe(**transcribe_args)
        transcribed_result.split_by_length(max_words=15)
        transcribed_result.to_srt_vtt(recognized_srt_path)

        detected_lang = transcribed_result.language
        write_file(lang_cache_path, detected_lang)

        return detected_lang, recognized_srt_path

    except Exception as e:
        print(f"[ERROR] Transcription failed on {device}: {str(e)}")
        
        # Fallback strategy
        if device in ["cuda"]:
            print("[INFO] Hardware acceleration failed, falling back to CPU...")
            return transcribe_with_whisper(
                audio_path, recognized_srt_path, lang_cache_path,
                voice_separation=voice_separation,
                force_cpu=True
            )
        raise e