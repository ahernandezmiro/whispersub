import os
import subprocess
import sys
import tempfile

from .cache import atomic_output_path, build_manifest, cache_is_valid, write_manifest
from .config import AudioExtractionConfig

def extract_audio(input_mkv, output_wav, audio_track_index=0, sample_rate=16000, channels=1):
    """
    Extract the specified audio track from MKV into a WAV with ffmpeg.
    Skips if output_wav already exists.
    """
    config = AudioExtractionConfig(
        track_index=audio_track_index,
        sample_rate=sample_rate,
        channels=channels,
    )
    manifest = build_manifest("audio-extraction", input_mkv, config.as_cache_dict())
    if cache_is_valid(output_wav, manifest):
        print(f"[INFO] Audio extraction: '{output_wav}' already exists.")
        return

    with atomic_output_path(output_wav) as temporary_output:
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_mkv,
            "-map", f"0:{audio_track_index}",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-c:a", config.codec,
            temporary_output,
        ]
        print("[INFO] Extracting audio with ffmpeg:", " ".join(cmd))
        subprocess.run(cmd, check=True)
    write_manifest(output_wav, manifest)


def separate_vocals(input_audio, output_wav, device="cpu", model="htdemucs"):
    """Create and cache a 16 kHz mono Demucs vocals stem."""
    manifest = build_manifest(
        "voice-separation",
        input_audio,
        {"model": model, "sample_rate": 16000, "channels": 1},
    )
    if cache_is_valid(output_wav, manifest):
        print(f"[INFO] Voice separation: '{output_wav}' already exists.")
        return output_wav

    parent = os.path.dirname(os.path.abspath(output_wav))
    track_name = os.path.splitext(os.path.basename(input_audio))[0]
    with tempfile.TemporaryDirectory(prefix=".demucs.", dir=parent) as demucs_output:
        command = [
            sys.executable,
            "-m", "demucs",
            "--two-stems=vocals",
            "-n", model,
            "-d", device,
            "-o", demucs_output,
            input_audio,
        ]
        print("[INFO] Separating vocals with Demucs:", " ".join(command))
        subprocess.run(command, check=True)
        vocals_path = os.path.join(demucs_output, model, track_name, "vocals.wav")
        if not os.path.isfile(vocals_path):
            raise RuntimeError(f"Demucs did not create the expected vocals stem: {vocals_path}")
        with atomic_output_path(output_wav) as temporary_output:
            resample_command = [
                "ffmpeg", "-y", "-i", vocals_path,
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                temporary_output,
            ]
            subprocess.run(resample_command, check=True)
    write_manifest(output_wav, manifest)
    return output_wav
