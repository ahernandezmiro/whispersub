"""
Requires:
- pykakasi (for Japanese romanization)
- pypinyin (for Chinese romanization)
- arabic-reshaper, python-bidi (for Arabic romanization)
"""

# Module-level converter for Japanese romanization (initialized once)
_japanese_converter = None
def _get_japanese_converter():
    global _japanese_converter
    if _japanese_converter is None:
        try:
            from pykakasi import kakasi
            kks = kakasi()
            kks.setMode("H", "a")
            kks.setMode("K", "a")
            kks.setMode("J", "a")
            kks.setMode("r", "Hepburn")
            kks.setMode("s", True)
            _japanese_converter = kks.getConverter()
        except ImportError:
            print("[WARNING] pykakasi library not installed. Japanese romanization unavailable.")
            _japanese_converter = None
    return _japanese_converter

def japanese_to_hepburn(text):
    converter = _get_japanese_converter()
    if converter is None:
        return text
    
    try:
        return converter.do(text)
    except Exception as e:
        print(f"[WARNING] Japanese romanization failed: {e}")
        return text

def russian_to_latin(text):
    # Russian to Latin transliteration mapping
    cyrillic_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        # Uppercase letters
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    
    result = ""
    for char in text:
        result += cyrillic_to_latin.get(char, char)
    return result

def chinese_to_pinyin(text):
    try:
        import pypinyin
        pinyin_list = pypinyin.pinyin(text, style=pypinyin.Style.TONE)
        pinyin_text = ' '.join([item[0] for item in pinyin_list])
        return pinyin_text
    except ImportError:
        print("[WARNING] pypinyin library not installed. Chinese romanization unavailable.")
        return text
    except Exception as e:
        print(f"[WARNING] Chinese romanization failed: {e}")
        return text

def arabic_to_latin(text):
    # Arabic to Latin transliteration mapping
    arabic_to_latin = {
        # Basic letters
        'ا': 'a', 'آ': 'aa', 'أ': 'a', 'إ': 'i', 'ء': "'",
        'ب': 'b', 'ت': 't', 'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh',
        'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
        'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': "'", 'غ': 'gh',
        'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
        'ه': 'h', 'ة': 'h', 'و': 'w', 'ؤ': "'", 'ي': 'y', 'ى': 'a',
        'ئ': "'",
        # Vowel marks (harakat)
        'َ': 'a', 'ً': 'an',  # fatha, tanween fath
        'ُ': 'u', 'ٌ': 'un',  # damma, tanween damm
        'ِ': 'i', 'ٍ': 'in',  # kasra, tanween kasr
        'ْ': '',  # sukoon
        'ّ': '',  # shadda - doubles the letter before it
        # Special ligatures
        'ﻻ': 'la', 'ﷲ': 'allah',
        # Numbers
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
    }
    
    try:
        result = []
        i = 0
        while i < len(text):
            char = text[i]
            next_char = text[i + 1] if i + 1 < len(text) else None
            
            # Handle shadda (consonant doubling)
            if next_char == 'ّ':
                if char in arabic_to_latin:
                    result.append(arabic_to_latin[char] * 2)
                else:
                    result.append(char * 2)
                i += 2
                continue
            
            # Handle normal characters
            if char in arabic_to_latin:
                # Special handling for alif with hamza
                if char in ['أ', 'إ'] and next_char and next_char in arabic_to_latin:
                    result.append(arabic_to_latin[char])
                # Normal character transliteration
                else:
                    result.append(arabic_to_latin[char])
            else:
                # Keep non-Arabic characters as is
                result.append(char)
            
            i += 1
        
        return ''.join(result)
        
    except Exception as e:
        print(f"[WARNING] Arabic romanization failed: {e}")
        return text

def korean_to_roman(text):
    # Korean Jamo ranges
    HANGUL_START = 0xAC00
    HANGUL_END = 0xD7A3
    JAMO_START = 0x1100
    JAMO_END = 0x11FF
    
    # Korean to Roman transliteration mapping (Revised Romanization)
    initial_consonants = {
        0: 'g', 1: 'gg', 2: 'n', 3: 'd', 4: 'dd', 5: 'r', 6: 'm', 7: 'b',
        8: 'bb', 9: 's', 10: 'ss', 11: '', 12: 'j', 13: 'jj', 14: 'ch',
        15: 'k', 16: 't', 17: 'p', 18: 'h'
    }
    
    medial_vowels = {
        0: 'a', 1: 'ae', 2: 'ya', 3: 'yae', 4: 'eo', 5: 'e', 6: 'yeo', 7: 'ye',
        8: 'o', 9: 'wa', 10: 'wae', 11: 'oe', 12: 'yo', 13: 'u', 14: 'wo',
        15: 'we', 16: 'wi', 17: 'yu', 18: 'eu', 19: 'yi', 20: 'i'
    }
    
    final_consonants = {
        0: '', 1: 'g', 2: 'gg', 3: 'gs', 4: 'n', 5: 'nj', 6: 'nh', 7: 'd',
        8: 'l', 9: 'lg', 10: 'lm', 11: 'lb', 12: 'ls', 13: 'lt', 14: 'lp',
        15: 'lh', 16: 'm', 17: 'b', 18: 'bs', 19: 's', 20: 'ss', 21: 'ng',
        22: 'j', 23: 'ch', 24: 'k', 25: 't', 26: 'p', 27: 'h'
    }
    
    result = []
    for char in text:
        char_code = ord(char)
        
        # Check if it's a Hangul syllable
        if HANGUL_START <= char_code <= HANGUL_END:
            # Convert to jamo indices
            char_code -= HANGUL_START
            final = char_code % 28
            medial = (char_code // 28) % 21
            initial = char_code // 28 // 21
            
            # Build romanized syllable
            romanized = initial_consonants[initial]
            romanized += medial_vowels[medial]
            if final > 0:  # Only add final consonant if it exists
                romanized += final_consonants[final]
            
            result.append(romanized)
        else:
            # For non-Hangul characters (punctuation, spaces, etc.)
            result.append(char)
    
    return ''.join(result)

def greek_to_latin(text):
    # Greek to Latin transliteration mapping
    greek_to_latin = {
        # Lowercase letters
        'α': 'a', 'β': 'v', 'γ': 'g', 'δ': 'd', 'ε': 'e', 'ζ': 'z', 'η': 'i',
        'θ': 'th', 'ι': 'i', 'κ': 'k', 'λ': 'l', 'μ': 'm', 'ν': 'n', 'ξ': 'x',
        'ο': 'o', 'π': 'p', 'ρ': 'r', 'σ': 's', 'τ': 't', 'υ': 'y', 'φ': 'f',
        'χ': 'ch', 'ψ': 'ps', 'ω': 'o',
        # Uppercase letters
        'Α': 'A', 'Β': 'V', 'Γ': 'G', 'Δ': 'D', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'I',
        'Θ': 'Th', 'Ι': 'I', 'Κ': 'K', 'Λ': 'L', 'Μ': 'M', 'Ν': 'N', 'Ξ': 'X',
        'Ο': 'O', 'Π': 'P', 'Ρ': 'R', 'Σ': 'S', 'Τ': 'T', 'Υ': 'Y', 'Φ': 'F',
        'Χ': 'Ch', 'Ψ': 'Ps', 'Ω': 'O'
    }
    
    result = ""
    for char in text:
        result += greek_to_latin.get(char, char)
    return result

def thai_to_latin(text):
    # Thai to Latin transliteration mapping (Royal Thai General System)
    thai_to_latin = {
        # Consonants
        'ก': 'k', 'ข': 'kh', 'ฃ': 'kh', 'ค': 'kh', 'ฅ': 'kh', 'ฆ': 'kh', 'ง': 'ng',
        'จ': 'ch', 'ฉ': 'ch', 'ช': 'ch', 'ซ': 's', 'ฌ': 'ch', 'ญ': 'y', 'ฎ': 'd',
        'ฏ': 't', 'ฐ': 'th', 'ฑ': 'th', 'ฒ': 'th', 'ณ': 'n', 'ด': 'd', 'ต': 't',
        'ถ': 'th', 'ท': 'th', 'ธ': 'th', 'น': 'n', 'บ': 'b', 'ป': 'p', 'ผ': 'ph',
        'ฝ': 'f', 'พ': 'ph', 'ฟ': 'f', 'ภ': 'ph', 'ม': 'm', 'ย': 'y', 'ร': 'r',
        'ฤ': 'rue', 'ล': 'l', 'ฦ': 'lue', 'ว': 'w', 'ศ': 's', 'ษ': 's', 'ส': 's',
        'ห': 'h', 'ฬ': 'l', 'อ': '', 'ฮ': 'h',
        # Vowels
        'ะ': 'a', 'ั': 'a', 'า': 'a', 'ำ': 'am', 'ิ': 'i', 'ี': 'i', 'ึ': 'ue',
        'ื': 'ue', 'ุ': 'u', 'ู': 'u', 'เ': 'e', 'แ': 'ae', 'โ': 'o', 'ใ': 'ai',
        'ไ': 'ai', 'ๆ': '', 'ฯ': '', '๏': '', '๚': '', '๛': '',
        # Tone marks
        '่': '', '้': '', '๊': '', '๋': '',
        # Numbers
        '๐': '0', '๑': '1', '๒': '2', '๓': '3', '๔': '4', '๕': '5', '๖': '6', '๗': '7', '๘': '8', '๙': '9'
    }
    
    result = ""
    for char in text:
        result += thai_to_latin.get(char, char)
    return result

def indian_to_latin(text):
    # Devanagari to Latin transliteration mapping (ISO 15919)
    devanagari_to_latin = {
        # Vowels
        'अ': 'a', 'आ': 'ā', 'इ': 'i', 'ई': 'ī', 'उ': 'u', 'ऊ': 'ū', 'ऋ': 'ṛ',
        'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au',
        # Consonants
        'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ṅ', 'च': 'c', 'छ': 'ch',
        'ज': 'j', 'झ': 'jh', 'ञ': 'ñ', 'ट': 'ṭ', 'ठ': 'ṭh', 'ड': 'ḍ', 'ढ': 'ḍh',
        'ण': 'ṇ', 'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n', 'प': 'p',
        'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm', 'य': 'y', 'र': 'r', 'ल': 'l',
        'व': 'v', 'श': 'ś', 'ष': 'ṣ', 'स': 's', 'ह': 'h',
        # Vowel signs
        'ा': 'ā', 'ि': 'i', 'ी': 'ī', 'ु': 'u', 'ू': 'ū', 'ृ': 'ṛ', 'े': 'e',
        'ै': 'ai', 'ो': 'o', 'ौ': 'au', '्': '',
        # Numbers
        '०': '0', '१': '1', '२': '2', '३': '3', '४': '4', '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
    }
    
    result = ""
    for char in text:
        result += devanagari_to_latin.get(char, char)
    return result

class RomanizationConverter:
    def __init__(self, convert_func):
        self.convert_func = convert_func
    
    def romanize(self, text):
        try:
            return self.convert_func(text)
        except Exception as e:
            print(f"[WARNING] Romanization failed: {e}")
        return None

def romanization_converter(language):
    converter = None
    lang = language.lower()
    if lang in ["ja", "japanese"]:
        # Japanese romanization
        converter = RomanizationConverter(japanese_to_hepburn)
    elif lang in ["ru", "russian"]:
        # Russian romanization
        converter = RomanizationConverter(russian_to_latin)
    elif lang in ["zh", "chinese", "zh-cn", "zh-hans", "zh-hant"]:
        # Chinese romanization
        converter = RomanizationConverter(chinese_to_pinyin)
    elif lang in ["ar", "arabic"]:
        # Arabic romanization
        converter = RomanizationConverter(arabic_to_latin)
    elif lang in ["ko", "korean"]:
        # Korean romanization
        converter = RomanizationConverter(korean_to_roman)
    elif lang in ["el", "gr", "greek"]:
        # Greek romanization
        converter = RomanizationConverter(greek_to_latin)
    elif lang in ["th", "thai"]:
        # Thai romanization
        converter = RomanizationConverter(thai_to_latin)
    elif lang in ["hi", "hindi", "sa", "sanskrit"]:
        # Hindi/Sanskrit romanization
        converter = RomanizationConverter(indian_to_latin)
    return converter
