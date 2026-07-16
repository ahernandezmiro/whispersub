from dataclasses import dataclass


@dataclass(frozen=True)
class WhisperModelInfo:
    name: str
    memory_class: str


WHISPER_MODELS = {
    info.name: info
    for info in (
        WhisperModelInfo("tiny", "low"),
        WhisperModelInfo("base", "low"),
        WhisperModelInfo("small", "low"),
        WhisperModelInfo("medium", "medium"),
        WhisperModelInfo("large", "high"),
        WhisperModelInfo("large-v2", "high"),
        WhisperModelInfo("large-v3", "high"),
        WhisperModelInfo("turbo", "medium"),
    )
}


def valid_model_names():
    return tuple(WHISPER_MODELS)


def validate_model_name(model_name):
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("Whisper model must be a non-empty name or path")
    return model_name
