"""Language-code normalization for MKV metadata and Whisper."""


_ISO639_2_TO_WHISPER = {
    "afr": "af", "alb": "sq", "amh": "am", "ara": "ar",
    "arm": "hy", "asm": "as", "aze": "az", "bak": "ba",
    "baq": "eu", "bel": "be", "ben": "bn", "bod": "bo",
    "bos": "bs", "bre": "br", "bul": "bg", "bur": "my",
    "cat": "ca", "ces": "cs", "chi": "zh", "cym": "cy",
    "cze": "cs", "dan": "da", "deu": "de", "dut": "nl",
    "ell": "el", "eng": "en", "est": "et", "eus": "eu",
    "fao": "fo", "fas": "fa", "fin": "fi", "fra": "fr",
    "fre": "fr", "geo": "ka", "ger": "de", "glg": "gl",
    "gre": "el", "guj": "gu", "hat": "ht", "hau": "ha",
    "haw": "haw", "heb": "he", "hin": "hi", "hrv": "hr",
    "hun": "hu", "hye": "hy", "ice": "is", "ind": "id",
    "isl": "is", "ita": "it", "jav": "jw", "jpn": "ja",
    "kan": "kn", "kat": "ka", "kaz": "kk", "khm": "km",
    "kor": "ko", "lao": "lo", "lat": "la", "lav": "lv",
    "lin": "ln", "lit": "lt", "ltz": "lb", "mac": "mk",
    "mal": "ml", "mao": "mi", "mar": "mr", "may": "ms",
    "mkd": "mk", "mlg": "mg", "mlt": "mt",
    "mon": "mn", "mri": "mi", "msa": "ms", "mya": "my",
    "nep": "ne", "nld": "nl", "nno": "nn", "nor": "no",
    "oci": "oc", "pan": "pa", "per": "fa", "pol": "pl",
    "por": "pt", "pus": "ps", "ron": "ro", "rum": "ro",
    "rus": "ru", "san": "sa", "sin": "si", "slk": "sk",
    "slo": "sk", "slv": "sl", "sna": "sn", "snd": "sd",
    "som": "so", "spa": "es", "sqi": "sq", "srp": "sr",
    "sun": "su", "swa": "sw", "swe": "sv", "tam": "ta",
    "tat": "tt", "tel": "te", "tgk": "tg", "tgl": "tl",
    "tha": "th", "tib": "bo", "tuk": "tk", "tur": "tr",
    "ukr": "uk", "urd": "ur", "uzb": "uz", "vie": "vi",
    "wel": "cy", "yid": "yi", "yor": "yo", "yue": "yue",
    "zho": "zh",
}

_WHISPER_LANGUAGE_CODES = frozenset(_ISO639_2_TO_WHISPER.values())


def normalize_language(value):
    """Convert a Whisper or ISO 639-2 language code to a Whisper code."""
    if not value:
        return None
    code = str(value).strip().lower()
    if not code or code in {"und", "zxx"}:
        return None

    base = code.replace("_", "-").split("-", 1)[0]
    if base in _WHISPER_LANGUAGE_CODES:
        return base
    return _ISO639_2_TO_WHISPER.get(base)


def supported_language_codes():
    return tuple(sorted(_WHISPER_LANGUAGE_CODES))
