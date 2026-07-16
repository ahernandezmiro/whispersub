from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AudioExtractionConfig:
    track_index: int = 1
    sample_rate: int = 16000
    channels: int = 1
    codec: str = "pcm_s16le"

    def as_cache_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TranscriptionConfig:
    model_name: str
    device: str
    compute_type: str
    voice_separation: bool = False
    vad: bool = True
    vad_threshold: float = 0.35
    word_timestamps: bool = True
    condition_on_previous_text: bool = True
    temperature: float = 0.0

    def as_cache_dict(self):
        return asdict(self)
