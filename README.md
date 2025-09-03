# 💬 WhisperSub: Automatic Transcription and Subtitle Merging for MKV Files

## Overview

WhisperSub is a command-line tool for automating the extraction, transcription, and merging of subtitles for MKV video files. It leverages state-of-the-art speech recognition ([stable-ts](https://github.com/jianfch/stable-ts)) and subtitle handling libraries to streamline the process of generating and synchronizing subtitles, including comprehensive support for romanization across multiple languages.

## Features

* **Audio Extraction**: Extracts audio tracks from MKV files using ffmpeg.
* **Automatic Transcription**: Uses Stable Whisper (stable-ts) to transcribe speech to text with improved accuracy, automatic language detection, and word-level timestamps.
* **Advanced Audio Processing**: Integrates with Demucs for speech isolation and noise reduction.
* **Subtitle Extraction**: Extracts existing subtitle tracks from MKV files.
* **Subtitle Merging**: Merges base subtitles (e.g., translations) with recognized (transcribed) subtitles, supporting multi-language and romanized output.
* **Comprehensive Romanization Support**: Automatically converts transcribed text to Latin characters for 8+ languages with optimized performance.
* **Flexible Input/Output**: Supports specifying audio/subtitle tracks or external subtitle files.
* **Sync Tolerance**: Adjustable timing tolerance for subtitle alignment.
* **Customizable styling**: Advanced font, size, color, margin, bold & italics options for transcribed & romanized subtitles

## Installation

### 1. System Dependencies

You must install `ffmpeg` and `mkvtoolnix` (for `mkvextract` and `mkvinfo`).

#### On Linux (Debian/Ubuntu/WSL):

```bash
sudo apt update
sudo apt install ffmpeg mkvtoolnix mkvtoolnix-gui mkvtoolnix-cli
```

#### On macOS (with Homebrew):

```bash
brew install ffmpeg mkvtoolnix
```

#### On Windows

1. Install `ffmpeg` and `mkvtoolnix` via Chocolatey (if using PowerShell):

   ```powershell
   choco install ffmpeg mkvtoolnix
   ```

2. Or download installer/binaries manually from their websites and add to `PATH`.

### 2. Python Environment Setup

Choose one of the following based on your system and whether you want GPU acceleration.

#### ⚙️ CPU-only:

```bash
pip install -r requirements.txt
```

#### ⚙️ GPU (CUDA 11.8):

```bash
pip install -r requirements-gpu.txt
pip install -r requirements.txt
```

If you face issues with PyTorch or CUDA DLLs, consider switching to the Conda installation below.

#### ⚙️ Conda (CUDA 11.8 support):

```bash
conda create -n whispersub python=3.10 pytorch=2.2.2 torchaudio=2.2.2 pytorch-cuda=11.8 cudnn -c pytorch -c nvidia
conda activate whispersub
pip install -r requirements-gpu.txt
pip install -r requirements.txt
```

## Usage

Run the tool from the command line:

```bash
python whispersub.py --i <input.mkv> [--o <output.ass>] [--transcribe] [--merge] [options]
```

### Main Options

* `--i` : Path to input MKV file (required)
* `--o` : Output subtitle filename for the merged subs
* `--transcribe` : Run transcription on the input file
* `--merge` : Merge subtitles into a single file
* `--clear-cache` : Clear cached files for the input file before processing

### Transcription Options

* `--audio-track` : Index of the audio track to extract (default: 1)
* `--whisper-model` : Stable Whisper model to use: tiny, base, small, medium, large, large-v2, large-v3. If not specified, the model is automatically selected based on your system's capabilities and available memory. Larger models provide better accuracy but require more memory and processing time.
* `--force-cpu` : Force CPU usage for transcription even if CUDA is available. Useful for debugging or when GPU memory is limited
* `--romanize` : Enable romanization for supported languages
* `--word-level` : Enable word-level timestamps in transcription
* `--voice-separation` : Enable voice separation (Demucs) during transcription. Slows transcription while improving results

### Merging Options

* `--subtitle-track` : Index of the base subtitle track to extract from MKV
* `--base-subs` : Path to existing base subtitle file (alternative to --subtitle-track)
* `--merge-track` : Index of the second subtitle track (required for merge-only mode)
* `--merge-subs` : Path to existing secondary subtitle file (required for merge-only mode, alternative to --merge-track)
* `--sync-tolerance` : Sync tolerance in milliseconds for merging subtitle(default=200)
* `--disable-layers` : Disable smart subtitle layering mode. By default, the application will try to position subtitles intelligently to avoid overlap while maintaining readability. When disabled, subtitles will be rendered in a single layer which may result in wrong order of the text but prevents the overlapping subtitle lines.

### Examples

#### 1. Transcribe with romanization

Transcribe audio with automatic romanization:

```bash
python whispersub.py --i examples\japanese.mkv --transcribe --romanize --o examples\japanese_transcription-romanized.ass
```

#### 2. Transcribe and merge

Transcribe audio and merge with existing subtitles:

```bash
python whispersub.py --i examples\japanese.mkv --transcribe --merge --base-subs examples\japanese_translation.ass --romanize --o examples\japanese_merged.ass
```

#### 3. Word level transcription

Merge two existing subtitle tracks without transcription:

```bash
python whispersub.py --i examples\deutsch.mkv --transcribe --word-level --o examples\deutsch_transcribed-wordlevel.ass
```

#### 3. Merge two existing subtitles

Merge two existing subtitle tracks without transcription:

```bash
python whispersub.py --i examples\deutsch.mkv --merge --base-subs examples\deutsch_transcribed.ass --merge-subs examples\deutsch_translated.ass
```

## 🈳 Romanization Support

WhisperSub supports automatic romanization (conversion to Latin characters) for 8+ languages. When the `--romanize` flag is used, the tool creates dual-language subtitles with both original and romanized text.

### Supported Languages

| Language | Code       | Implementation          | Standard                  | Example                 |
| -------- | ---------- | ----------------------- | ------------------------- | ----------------------- |
| Chinese  | `zh`       | pypinyin (tone numbers) | Hanyu Pinyin              | 你好 → nǐ hǎo             |
| Standard Arabic   | `ar`       | Arabic to Latin         | ISO 233                   | مرحبا → marhaba         |
| Hindi    | `hi`, `sa` | Devanagari to Latin     | ISO 15919                 | नमस्ते → namaste        |
| Japanese | `ja`       | pykakasi (Hepburn)      | Hepburn                   | こんにちは → konnichiha      |
| Korean   | `ko`       | Hangul to Latin         | Revised Romanization      | 안녕하세요 → annyeonghaseyo  |
| Russian  | `ru`       | Cyrillic to Latin       | GOST 7.79-2000            | Привет мир → Privet mir |
| Thai     | `th`       | Thai to Latin           | Royal Thai General System | สวัสดี → sawatdi        |
| Greek    | `el`, `gr` | Greek to Latin          | ISO 843                   | Γεια σας → Geia sas     |

### Custom Styling Options

You can customize the appearance of both transcribed and romanized subtitles using the following options:

For Transcription:
- `--trans-font`: Font name (e.g., "Arial")
- `--trans-size`: Font size. Accepts:
  - Absolute values: Direct pixel size (e.g., 24)
  - Relative multiplier: Multiply base size (e.g., *0.85 for 85% of base size)
  - Relative addition/subtraction: Add/subtract from base size (e.g., +2 or -2)
- `--trans-margin`: Vertical margin from the bottom of the screen. Accepts:
  - Absolute values: Direct pixel distance (e.g., 20)
  - Relative multiplier: Multiply base margin (e.g., *1.5 for 150% of base margin)
  - Relative addition/subtraction: Add/subtract from base margin (e.g., +10 or -5)
- `--trans-color`: Text color in hex format (e.g., FFFFFF for white)
- `--trans-bold`: Use bold font
- `--trans-italic`: Use italic font
- `--highlight-color`: Color to use when word-level rendering is enabled. Defaults to 00FF00.

For Romanization:
- `--rom-font`: Font name for romanized text (e.g., "Arial")
- `--rom-size`: Font size for romanized text. Same format as --trans-size
- `--rom-margin`: Vertical margin from the bottom of the screen. Same format as --trans-margin
- `--rom-color`: Color for romanized text in hex format (e.g., FFFFFF for white)
- `--rom-bold`: Use bold font for romanized text
- `--rom-italic`: Use italic font for romanized text. True by default

## Troubleshooting

### Common Issues and Solutions

#### CUDA DLL Issues

1. **Missing cublas64_12.dll**
   ```bash
   Error: Library cublas64_12.dll is not found or cannot be loaded
   ```
   Solution: Reinstall ctranslate2 with the correct version:
   ```bash
   pip install --upgrade --force-reinstall ctranslate2==3.24.0
   ```

2. **Missing cudnn DLLs**
   ```bash
   Error: Could not load library cudnn_ops_infer64_8.dll. Error code 126
   ```
   Solution: 
   1. Download the CUDA toolkit from NVIDIA's website
   2. Extract the downloaded zip file
   3. Copy the affected dll files from the `bin` folder into your nvidia gpu computing toolkit\cuda\bin folder

## About Transcription & Merging Accuracy

### Transcription
The accuracy of the transcription is determined by the underlying Whisper AI model. While the model is highly capable, it's important to note that:

1. The transcription will never be 100% perfect and you may find instances where:
   - Words can be misheard or misinterpreted
   - Lines may be repeated and/or ommited
   - Background noise can interfere with recognition
   - Numbers and proper nouns may add complexity to the task

2. To improve transcription accuracy:
   - Use the `--voice-separation` option to isolate voice from background noise
   - Choose a larger model (e.g., `large-v3`) for better accuracy at the cost of speed

The model will automatically be selected based on your system's capabilities, but you can override this with the `--whisper-model` option.

### Subtitle merging

The subtitle merging process employs a smart positioning algorithm to handle multiple subtitle tracks effectively:

1. ASS Format Recommended:
   - The ASS subtitle format is strongly recommended for best results
   - If SRT is specified in the output filename:
     - All ASS styling information will be lost
     - Subtitle ordering cannot be guaranteed
     - Advanced positioning features will not be available

2. Smart Positioning:
   - The algorithm intelligently repositions subtitles to avoid overlap
   - Timing-based synchronization uses the specified sync tolerance
   - Smart layering helps maintain readability when multiple lines appear simultaneously

3. Overlap Handling:
   - By default, smart layering is enabled to handle overlapping subtitles
   - If you experience issues with subtitle ordering, you can use `--disable-layers`
   - Note that disabling layers may affect the visual presentation of concurrent subtitles

## License

MIT License

## Acknowledgements

* [Stable Whisper (stable-ts)](https://github.com/jianfch/stable-ts) - Enhanced Whisper implementation with improved accuracy and word-level timestamps
* [ffmpeg](https://ffmpeg.org/) - Audio and video processing toolkit
* [mkvtoolnix](https://mkvtoolnix.download/) - MKV manipulation tools
* [pysubs2](https://github.com/tkarabela/pysubs2) - Subtitle file handling
* [pykakasi](https://github.com/miurahr/pykakasi) - Japanese romanization
* [pypinyin](https://github.com/mozillazg/python-pinyin) - Chinese romanization
* [arabic-reshaper](https://github.com/mpcabd/python-arabic-reshaper) - Arabic text processing
* [python-bidi](https://github.com/MeirKriheli/python-bidi) - Bidirectional text support
