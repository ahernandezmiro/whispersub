import subprocess

from .utils import file_exists

def extract_audio(input_mkv, output_wav, audio_track_index=0, sample_rate=44100):
    """
    Extract the specified audio track from MKV into a WAV with ffmpeg.
    Skips if output_wav already exists.
    """
    if file_exists(output_wav):
        print(f"[INFO] Audio extraction: '{output_wav}' already exists.")
        return

    cmd = [
        "ffmpeg",
        "-y",  # overwrite
        "-i", input_mkv,
        "-map", f"0:{audio_track_index}",
        "-ar", str(sample_rate),
        "-ac", "2",
        "-c:a", "pcm_s16le",
        output_wav
    ]
    print("[INFO] Extracting audio with ffmpeg:", " ".join(cmd))
    subprocess.run(cmd, check=True)
