#!/usr/bin/env python3
import os
import argparse
import platform
import shutil
import sys
import re

from src.audio import extract_audio, get_audio_track_language
from src.transcription import transcribe_with_whisper
from src.subtitles import extract_subtitles, merge_subtitles
from src.utils import clear_cache_for_file, file_exists, temp_dir

def verify_command_line_tools(args):
    """Verify that all required command-line tools are installed and accessible."""
    required_tools = {}
    if args.transcribe:
        required_tools['ffmpeg'] = 'ffmpeg'
    needs_subtitle_extraction = args.merge and (
        not args.base_subs or (not args.transcribe and not args.merge_subs)
    )
    if needs_subtitle_extraction:
        required_tools['mkvextract'] = 'mkvextract'
    if args.merge and not args.base_subs and args.subtitle_track is None:
        required_tools['mkvinfo'] = 'mkvinfo'
    
    if platform.system() == "Windows":
        required_tools = {k: f"{v}.exe" for k, v in required_tools.items()}
    
    missing_tools = []
    for tool_name, executable in required_tools.items():
        if shutil.which(executable) is None:
            missing_tools.append(tool_name)
    
    if missing_tools:
        print("[ERROR] The following required command-line tools are not installed or not in PATH:")
        for tool in missing_tools:
            print(f"  - {tool}")
        print("\nPlease install the missing tools and ensure they are available in your system PATH.")
        sys.exit(1)

def validate_inputs(args):
    """Validate all input arguments and file paths."""
    if not file_exists(args.i):
        print(f"[ERROR] Input file '{args.i}' does not exist.")
        sys.exit(1)
    
    if not args.i.lower().endswith('.mkv'):
        print("[ERROR] Input file must be an MKV file.")
        sys.exit(1)
    
    if args.audio_track <= 0:
        print("[ERROR] Audio track index must be greater than 0.")
        sys.exit(1)
    
    if args.subtitle_track is not None and args.subtitle_track <= 1:
        print("[ERROR] Subtitle track index must be greater than 1.")
        sys.exit(1)
    
    if args.merge_track is not None and args.merge_track <= 1:
        print("[ERROR] Merge track index must be greater than 1.")
        sys.exit(1)
    
    if args.base_subs and not file_exists(args.base_subs):
        print(f"[ERROR] Base subtitles file '{args.base_subs}' does not exist.")
        sys.exit(1)
    
    if args.merge_subs and not file_exists(args.merge_subs):
        print(f"[ERROR] Merge subtitles file '{args.merge_subs}' does not exist.")
        sys.exit(1)

    def validate_color(color):
        if color and (not re.match(r'^[0-9A-Fa-f]{6}$', color)):
            print(f"[WARNING] Invalid color format. Must be 6 hexadecimal characters (e.g., FFFFFF for white)")
            sys.exit(1)
        return color
    
    def validate_number_expression(expression):
        if expression and (not re.match(r'^[\+\-\*]?\d+(\.\d+)?$', expression)):
            print(f"[WARNING] Invalid number expression '{expression}'. Must be an absolute number (e.g., 24), a relative multiplier (e.g., *0.85), or a relative addition/subtraction (e.g., +2 or -2).")
            sys.exit(1)
        return expression
    
    def validate_font(font):
        if font and (not isinstance(font, str) or len(font.strip()) == 0):
            print(f"[WARNING] Invalid font name specified.")
            sys.exit(1)
        return font

    if args.trans_font:
        validate_font(args.trans_font)
    if args.trans_size:
        validate_number_expression(args.trans_size)
    if args.trans_margin:
        validate_number_expression(args.trans_margin)
    if args.trans_color:
        validate_color(args.trans_color)
    if args.highlight_color:
        if not args.word_level:
            print(f"[WARNING] --highlight-color only applies when --word-level is enabled. Parameter will be ignored.")
        else:
            validate_color(args.highlight_color)
    
    if args.rom_font:
        validate_font(args.rom_font)
    if args.rom_size:
        validate_number_expression(args.rom_size)
    if args.rom_margin:
        validate_number_expression(args.rom_margin)
    if args.rom_color:
        validate_color(args.rom_color)

def main():
    parser = argparse.ArgumentParser(
        description="Automatic transcription and subtitle generation for MKV files."
    )
    
    # Input/output options
    parser.add_argument("--i", help="Path to input MKV file.", required=True)
    parser.add_argument("--o",
                        help="Output subtitle filename for the merged subs.")
    
    # Operation mode
    parser.add_argument("--transcribe", action="store_true",
                        help="Run transcription on the input file.")
    parser.add_argument("--merge", action="store_true",
                        help="Merge subtitles into a single SRT file.")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear cached files for the input file before processing.")
    
    # Transcription options
    transcription_group = parser.add_argument_group("Transcription options")
    transcription_group.add_argument("--audio-track", type=int, default=1,
                        help="Index of the audio track to extract (default=1).")
    transcription_group.add_argument("--whisper-model", type=str,
                        help="Whisper model name or compatible Faster-Whisper model path (built-ins: tiny, base, small, medium, large, large-v2, large-v3, turbo).")
    transcription_group.add_argument("--language", type=str,
                        help="Whisper language code override (for example: ja, en, ko). Skips automatic language detection.")
    transcription_group.add_argument("--force-cpu",
                        help="Force CPU usage for transcription.", action="store_true")    
    transcription_group.add_argument("--romanize", action="store_true",
                        help="Enable romanization")
    transcription_group.add_argument("--word-level", action="store_true",
                        help="Highlight individual words with their exact timestamps. This can be useful for karaoke-style subtitles or precise word timing")
    transcription_group.add_argument("--voice-separation", action="store_true",
                        help="Enable Demucs AI model to separate voice from background noise before transcription. This improves accuracy but increases processing time significantly")
    
    # Merging options
    subtitle_group = parser.add_argument_group("Merging options")
    subtitle_group.add_argument("--subtitle-track", type=int,
                        help="Index of the base subtitle track to extract from MKV.")
    subtitle_group.add_argument("--base-subs",
                        help="Path to existing base subtitles file (alternative to --subtitle-track).")
    subtitle_group.add_argument("--merge-track", type=int,
                        help="Index of the second subtitle track (required for merge-only mode).")
    subtitle_group.add_argument("--merge-subs",
                        help="Path to existing secondary subtitles file (required for merge-only mode, alternative to --merge-track).")
    subtitle_group.add_argument("--sync-tolerance", type=int, default=200,
                        help="Sync tolerance in milliseconds for merging subtitles (default=200).")
    subtitle_group.add_argument("--disable-layers", action="store_true",
                        help="Disable smart subtitle layering mode. Read more in README.")
    
    # Style customization options
    style_group = parser.add_argument_group("Style options")
    style_group.add_argument("--trans-font", help="Font name for transcription text (e.g., Arial)")
    style_group.add_argument("--trans-size", type=str, 
                            help="Font size for transcription text. Accepts absolute values (e.g., 24), relative multipliers (*0.85), or relative additions/subtractions (+2/-2). Default: *0.85")
    style_group.add_argument("--trans-margin", type=str, 
                            help="Vertical margin from bottom for transcription. Accepts absolute pixels (e.g., 20), relative multipliers (*1.5), or relative additions/subtractions (+10/-5). Default: *1.0")
    style_group.add_argument("--trans-color", help="Color for transcription text in hex format (e.g., FFFFFF for white)")
    style_group.add_argument("--trans-bold", action="store_true", help="Use bold font for transcription")
    style_group.add_argument("--trans-italic", action="store_true", help="Use italic font for transcription")
    style_group.add_argument("--highlight-color", help="Color for highlighted transcription text in hex format. Default: 00FF00")
    
    style_group.add_argument("--rom-font", help="Font name for romanization text (e.g., Arial)")
    style_group.add_argument("--rom-size", type=str,
                            help="Font size for romanization text. Same format as --trans-size. Default: *0.6")
    style_group.add_argument("--rom-margin", type=str,
                            help="Vertical margin from bottom for romanization text. Same format as --trans-margin. Default: *1.0")
    style_group.add_argument("--rom-color", help="Color for romanization text in hex format (e.g., FFFFFF for white)")
    style_group.add_argument("--rom-bold", action="store_true", help="Use bold font for romanization")
    style_group.add_argument("--rom-italic", action="store_true", help="Use italic font for romanization")

    args = parser.parse_args()

    validate_inputs(args)

    if not (args.transcribe or args.merge):
        parser.error("At least one of --transcribe or --merge must be specified")
    
    if not args.i:
        parser.error("--i is required")

    verify_command_line_tools(args)
    
    if args.merge:

        # Check just one or the other parameter is set for base subs
        if args.base_subs and args.subtitle_track:
            parser.error("Cannot specify both --subtitle-track and --base-subs")

        if not args.transcribe and not(args.merge_track or args.merge_subs):
            parser.error("Either --merge-track or --merge-subs is required when using --merge without --transcribe") 

        # Check just one or the other parameter is set for merge subs
        if args.merge_track and args.merge_subs:
            parser.error("Cannot specify both --merge-track and --merge-subs")


    file_input_path = args.i

    # Create temp directory
    _, filename = os.path.split(os.path.splitext(file_input_path)[0])

    # Clear cache if requested
    if args.clear_cache:
        clear_cache_for_file(filename, file_input_path)

    output_subs_path = args.o or f"{filename}.ass"
    file_tmp_dir = temp_dir(filename, file_input_path)
    
    transcribed_subs_path = None
    transcription_result_path = None
    detected_lang = None
    
    if args.transcribe:
        raw_audio_path = os.path.join(file_tmp_dir, f'{args.audio_track}_extracted.wav')
        extract_audio(file_input_path, raw_audio_path, audio_track_index=args.audio_track)
        metadata_language = None
        if not args.language:
            metadata_language = get_audio_track_language(
                file_input_path, args.audio_track)
        
        input_for_whisper = raw_audio_path
        
        transcribed_subs_path = os.path.join(file_tmp_dir, f'{args.audio_track}_transcribed.srt')
        transcription_result_path = os.path.join(file_tmp_dir, f'{args.audio_track}_transcribed.json')
        lang_cache_path = os.path.join(file_tmp_dir, f'{args.audio_track}_detected_lang.txt')
        detected_lang, transcribed_subs_path = transcribe_with_whisper(
            input_for_whisper,
            recognized_srt_path=transcribed_subs_path,
            lang_cache_path=lang_cache_path,
            model_name=args.whisper_model,
            voice_separation=args.voice_separation,
            force_cpu=args.force_cpu,
            language=args.language,
            metadata_language=metadata_language,
            result_json_path=transcription_result_path,
        )

    base_subs_path = None
    second_subs_path = None

    if args.merge:
        # Handle base subtitles
        if args.base_subs:
            base_subs_path = args.base_subs
        elif args.subtitle_track:
            # Extract base subs from MKV
            base_subs_path = os.path.join(file_tmp_dir, f'{args.subtitle_track}_subs.srt')
            extract_subtitles(file_input_path, base_subs_path, subtitle_track_index=args.subtitle_track)
        else:
            base_subs_path = os.path.join(file_tmp_dir, f'[subtitle_track]_subs.srt')
            base_subs_path = extract_subtitles(file_input_path, base_subs_path)

        if not args.transcribe:
            # Handle secondary subtitles
            if args.merge_track:
                # Extract base subs from MKV
                second_subs_path = os.path.join(file_tmp_dir, f'{args.merge_track}_subs.srt')
                extract_subtitles(file_input_path, second_subs_path, subtitle_track_index=args.merge_track)
            else:
                second_subs_path = args.merge_subs
        
    render_transcription = args.transcribe and (
        args.romanize or not args.word_level or output_subs_path.lower().endswith('.ass')
    )
    if args.merge or render_transcription:

        style_config = {
            'transcription': {},
            'romanization': {}
        }

        if args.trans_font: style_config['transcription']['fontname'] = args.trans_font
        if args.trans_size: style_config['transcription']['fontsize'] = args.trans_size
        elif args.merge and args.transcribe: style_config['transcription']['fontsize'] = '*0.85'
        if args.trans_margin: style_config['transcription']['marginv'] = args.trans_margin
        if args.trans_color: style_config['transcription']['primarycolor'] = args.trans_color
        if args.trans_color: style_config['transcription']['secondarycolor'] = args.trans_color
        if args.highlight_color: style_config['transcription']['highlightcolor'] = args.highlight_color
        if args.trans_bold: style_config['transcription']['bold'] = True
        if args.trans_italic: style_config['transcription']['italic'] = True
        
        if args.rom_font: style_config['romanization']['fontname'] = args.rom_font
        if args.rom_size: style_config['romanization']['fontsize'] = args.rom_size
        elif args.merge and args.transcribe: style_config['romanization']['fontsize'] = '*0.6'
        if args.rom_margin: style_config['romanization']['marginv'] = args.rom_margin
        if args.rom_color: style_config['romanization']['primarycolor'] = args.rom_color
        if args.rom_color: style_config['romanization']['secondarycolor'] = args.rom_color
        if args.rom_bold: style_config['romanization']['bold'] = True
        if args.rom_italic: style_config['romanization']['italic'] = True

        merge_subtitles(
            base_subs_path=base_subs_path,
            second_subs_path=second_subs_path,
            transcribed_subs_path=transcribed_subs_path,
            transcription_result_path=transcription_result_path,
            output_subs_path=output_subs_path,
            detected_language=detected_lang,
            need_romanization=args.romanize,
            highlight_current_word=args.word_level,
            sync_tolerance=args.sync_tolerance,
            style_config=style_config,
            disable_layers=args.disable_layers,
        )
    elif args.transcribe:
        shutil.copy2(transcribed_subs_path, output_subs_path)
    
    print("[INFO] Done! Use '{}' when watching the video.".format(output_subs_path))

if __name__ == "__main__":
    main()
