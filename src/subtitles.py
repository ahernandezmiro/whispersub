import subprocess
import re
import json
import os
from bisect import bisect_left, bisect_right
import pysubs2

from .alignment import (
    AlignmentEvent,
    WordTiming,
    align_events,
    snap_times,
    split_words_across_bases,
)
from .cache import atomic_output_path, build_manifest, cache_is_valid, write_manifest
from .romanization import romanization_converter
from .utils import hex_to_binary

def extract_formatting_tags(text):
    # Patterns for common formatting tags - improved to handle ASS format better
    patterns = [
        # ASS color tags: {\c&HBBGGRR&} or {\c}
        (r'\\c&H[0-9a-fA-F]{6}&', r'\\c'),
        (r'\\c', r'\\c'),
        # HTML font tags: <font color="#RRGGBB"> or </font>
        (r'<font color="[^"]*">', r'<font>'),
        (r'</font>', r'</font>'),
        # Other ASS tags: \b, \i, \u, \s, \an, \pos, etc.
        (r'\\[biusan][0-9]*', r''),
        (r'\\pos\([^)]*\)', r''),
        (r'\\move\([^)]*\)', r''),
        (r'\\fad\([^)]*\)', r''),
        (r'\\fade\([^)]*\)', r''),
    ]
    
    clean_text = text
    tags_info = []
    
    for pattern, tag_type in patterns:
        matches = list(re.finditer(pattern, clean_text))
        # Process matches in reverse order to maintain positions
        for match in reversed(matches):
            start_pos = match.start()
            end_pos = match.end()
            original_tag = match.group(0)
            
            # Store tag info
            tags_info.append((tag_type, start_pos, end_pos, original_tag))
            
            # Remove tag from clean text
            clean_text = clean_text[:start_pos] + clean_text[end_pos:]
    
    # Sort tags by position for easier processing
    tags_info.sort(key=lambda x: x[1])
    
    return clean_text.strip(), tags_info

def reapply_formatting_tags(clean_text, tags_info):
    if not tags_info:
        return clean_text
    
    # For now, we'll apply tags at the beginning of the text
    # A more sophisticated approach would try to match positions based on character count
    formatted_text = clean_text
    
    # Apply color tags at the beginning
    color_tags = [tag for tag in tags_info if tag[0] in ['\\c', '<font>', '</font>']]
    if color_tags:
        # Find the first color tag and apply it
        for tag_type, _, _, original_tag in color_tags:
            if tag_type == '\\c' and original_tag != '\\c':
                # This is a color tag, apply it at the beginning
                formatted_text = original_tag + formatted_text
                break
    
    return formatted_text

def extract_subtitles(input_mkv, output_subs, subtitle_track_index=None):
    if subtitle_track_index is None:
        # Fetch the first subtitle track index from the mkv file using mkvinfo
        try:
            result = subprocess.run([
                "mkvinfo", input_mkv, "--ui-language", "en"
            ], capture_output=True, text=True, check=True)
            lines = result.stdout.splitlines()
            subtitle_index = None
            current_track_id = None
            is_subtitle = False
            for line in lines:
                line = line.strip()
                # Detect start of a track
                m = re.match(r".*\+ Track number: (\d+) \(track ID for mkvmerge & mkvextract: (\d+)\)", line)
                if m:
                    current_track_id = int(m.group(2))
                    is_subtitle = False
                elif '+ Track type: subtitles' in line:
                    is_subtitle = True
                # If we have both a track id and know it's a subtitle, that's our track
                if current_track_id is not None and is_subtitle:
                    subtitle_index = current_track_id
                    print(f"[INFO] Detected subtitle track index: {subtitle_index}")
                    break
            if subtitle_index is not None:
                subtitle_track_index = subtitle_index
                output_subs = output_subs.replace("[subtitle_track]", str(subtitle_track_index))
            else:
                raise RuntimeError("No subtitle track found in the MKV file.")
        except Exception as e:
            print(f"[ERROR] Failed to detect subtitle track index: {e}")
            raise

    manifest = build_manifest(
        "subtitle-extraction",
        input_mkv,
        {"track_index": subtitle_track_index},
    )
    if cache_is_valid(output_subs, manifest):
        print(f"[INFO] Subtitle extraction: '{output_subs}' already exists.")
        return output_subs
    

    # mkvextract tracks input.mkv subtitle_track_index:english_subs.srt
    with atomic_output_path(output_subs) as temporary_output:
        cmd = [
            "mkvextract",
            "tracks",
            input_mkv,
            f"{subtitle_track_index}:{temporary_output}"
        ]
        print("[INFO] Extracting subtitles with mkvextract:", " ".join(cmd))
        subprocess.run(cmd, check=True)
    write_manifest(output_subs, manifest)

    return output_subs


def html_font_to_ass(text, highlight_color=None):
    # Convert <font color="#RRGGBB"> to {\c&HBBGGRR&}
    def repl(match):
        color = match.group(1)
        # Convert #RRGGBB to BBGGRR (ASS format)
        if color.startswith("#") and len(color) == 7:
            rr = color[1:3]
            gg = color[3:5]
            bb = color[5:7]
            ass_color = f"&H{bb}{gg}{rr}&"
            return r"{\c" + ass_color + "}"
        return ""
    
    if highlight_color:
        text = re.sub(r'<font color="(#[0-9a-fA-F]{6})">', f'<font color="#{highlight_color}">', text)

    # Replace opening tag
    text = re.sub(r'<font color="(#[0-9a-fA-F]{6})">', repl, text)
    # Replace closing tag with ASS color reset to white (default color)
    text = text.replace('</font>', r"{\c}")
    return text

def aggregate_subtitle_lines(subs, max_gap=1000):
    aggregated_rec = []
    j = 0
    while j < len(subs):
        rec_event = subs[j]
        if not rec_event.text.strip():
            j += 1
            continue
            
        clean_text = extract_formatting_tags(rec_event.text)[0]
        agg_start = rec_event.start
        agg_end = rec_event.end
        
        # Look ahead for consecutive events with same cleaned text
        k = j + 1
        while k < len(subs):
            next_event = subs[k]
            if not next_event.text.strip():
                k += 1
                continue
                
            next_clean = extract_formatting_tags(next_event.text)[0]
            if next_clean != clean_text or next_event.start - agg_end > max_gap:
                break
                
            # Extend the aggregated event time
            agg_end = next_event.end
            k += 1
        
        # Create aggregated event
        agg_event = pysubs2.SSAEvent(
            start=agg_start,
            end=agg_end,
            text=rec_event.text,
            style=rec_event.style,
        )
        aggregated_rec.append(agg_event)
        j = k

    return aggregated_rec

def calculate_adjusted_style_properties(base_style, config, name_suffix, n_lines, trans_config=None, trans_lines=1):
    """
    Calculate adjusted style properties based on configuration and number of lines.
    
    Args:
        base_style: The base style to derive properties from
        config: Style configuration dictionary
        name_suffix: Style name suffix ("Transcription" or "Romanized")
        n_lines: Number of lines in the text
        trans_config: Optional transcription config for romanization margin calculation
        trans_lines: Number of lines in the transcription text
    """
    try:
        adjusted_config = config.copy()
        
        # Get base values
        base_fontsize = getattr(base_style, 'fontsize', None)
        trans_fontsize = 16

        base_marginv = getattr(base_style, 'marginv', None)
        
        # Set default values if not present
        if base_fontsize is None:
            base_fontsize = 16 if "Transcription" in name_suffix else 12
        if base_marginv is None:
            base_marginv = 10 if "Transcription" in name_suffix else 30

        for prop, value in config.items():
            if prop in ['fontsize', 'marginv'] and value is not None:
                base_value = getattr(base_style, prop, None)
                if base_value is None:
                    base_value = base_fontsize if prop == 'fontsize' else base_marginv
                
                if prop == 'marginv':
                    base_value = base_value * n_lines

                if isinstance(value, str):
                    try:
                        if value.startswith('+'):
                            adjusted_config[prop] = int(base_value + float(value[1:]))
                        if value.startswith('-'):
                            adjusted_config[prop] = int(base_value - float(value[1:]))
                        elif value.startswith('*'):
                            adjusted_config[prop] = int(base_value * float(value[1:]))
                        else:  # Absolute value
                            adjusted_config[prop] = int(float(value))
                    except (ValueError, ZeroDivisionError) as e:
                        print(f"[WARNING] Invalid format for {prop} value: {value}. Using base value. Error: {e}")
                        adjusted_config[prop] = base_value
                
                if prop == 'fontsize':
                    trans_fontsize = adjusted_config[prop]
            elif prop in ['primarycolor', 'secondarycolor']:
                adjusted_config[prop] = hex_to_binary(value)
            else:
                adjusted_config[prop] = value
                
        if "marginv" not in adjusted_config:
            if "Transcription" in name_suffix:
                adjusted_config["marginv"] = base_marginv + base_fontsize * n_lines
            elif "Romanized" in name_suffix and trans_config:
                adjusted_config["marginv"] = base_marginv + base_fontsize * n_lines + trans_fontsize * trans_lines + 7
            else:
                adjusted_config["marginv"] = base_marginv + base_fontsize * n_lines
        return adjusted_config
    except Exception as e:
        print(f"[ERROR] Failed to calculate adjusted style properties for {name_suffix}: {e}")
        return config

def create_style_if_not_exists(event, merged, name_suffix, style_properties):
    """
    Creates a new style based on the event's style with modified properties.
    """
    if event:
        base_style_name = event.style if event.style in merged.styles else "Default"
        base_style = merged.styles[base_style_name].copy()
        style_name = f"{name_suffix}_{base_style_name}"
        
        if style_name not in merged.styles:
            for prop, value in style_properties.items():
                base_style.__setattr__(prop, value)
            
            merged.styles[style_name] = base_style
        
        return style_name
    return None

def initialize_merged_file(subs_base=None):
    merged = pysubs2.SSAFile()
    
    if subs_base:
        # Copy all styles from base subtitles to preserve formatting
        for style_name, style in subs_base.styles.items():
            merged.styles[style_name] = style

        for info_name, info in subs_base.info.items():
            if str(info_name).lower() == "collisions":
                merged.info[info_name] = "Normal"
            elif str(info_name).lower() == "wrapstyle":
                merged.info[info_name] = 3
            else:
                merged.info[info_name] = info
                
    return merged

def initialize_default_styles(merged, style_config=None):
    trans_config = style_config.get("transcription", {}) if style_config else {}
    rom_config = style_config.get('romanization', {}) if style_config else {}
    
    if not "Default" in merged.styles:
        merged.styles["Default"] = pysubs2.SSAStyle(
            fontname='Arial',
            fontsize=18,
            bold=False,
            italic=False,
            underline=False,
            strikeout=False,
            outline=1,
            shadow=1,
            marginv=10,
            alignment=2,
            primarycolor=hex_to_binary('FFFFFF'),
            secondarycolor=hex_to_binary('FFFFFF'),
            outlinecolor=hex_to_binary("000000"),
            backcolor=hex_to_binary("000000"),
            borderstyle=1,
            scalex=100,
            scaley=100
        )
    if not "Secondary" in merged.styles:
        merged.styles["Secondary"] = merged.styles["Default"].copy()
        merged.styles["Secondary"].marginv = 30
        
    if not "Transcription" in merged.styles:
        font_size = trans_config.get('fontsize')
        if not font_size or str(font_size).startswith(('*', '+', '-')):
             font_size = 16
        merged.styles["Transcription"] = pysubs2.SSAStyle(
            fontname=trans_config.get('fontname', 'Arial'),
            fontsize=font_size,
            bold=trans_config.get('bold', False),
            italic=trans_config.get('italic', False),
            underline=False,
            strikeout=False,
            outline=1,
            shadow=1,
            marginv=30,
            alignment=2,
            primarycolor=hex_to_binary(trans_config.get('primarycolor', 'FFFFFF')),
            secondarycolor=hex_to_binary(trans_config.get('secondarycolor', 'FFFFFF')),
            outlinecolor=hex_to_binary("000000"),
            backcolor=hex_to_binary("000000"),
            borderstyle=1,
            scalex=100,
            scaley=100
        )
    if not "Romanized" in merged.styles:
        font_size = rom_config.get('fontsize')
        if not font_size or str(font_size).startswith(('*', '+', '-')):
             font_size = 12
        merged.styles["Romanized"] = pysubs2.SSAStyle(
            fontname=rom_config.get('fontname', 'Arial'),
            fontsize=font_size,
            bold=rom_config.get('bold', False),
            italic=rom_config.get('italic', True),
            underline=False,
            strikeout=False,
            outline=1,
            shadow=1,
            marginv=50,
            alignment=2,
            primarycolor=hex_to_binary(rom_config.get('primarycolor', 'BCBCBC')),
            secondarycolor=hex_to_binary(rom_config.get('secondarycolor', 'BCBCBC')),
            outlinecolor=hex_to_binary("000000"),
            backcolor=hex_to_binary("000000"),
            borderstyle=1,
            scalex=100,
            scaley=100
        )

def try_load_subtitles(file_path):
    if not file_path:
        return []
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
    except OSError as error:
        raise ValueError(f"Failed to read {file_path}: {error}") from error

    encodings = []
    if raw_data.startswith((b'\xff\xfe', b'\xfe\xff')):
        encodings.append('utf-16')
    encodings.extend([
        'utf-8-sig', 'utf-16-le', 'utf-16-be',
        'cp932', 'shift_jis', 'euc_jp', 'cp1252',
    ])
    errors = []
    for encoding in dict.fromkeys(encodings):
        try:
            content = raw_data.decode(encoding, errors='strict')
            try:
                return pysubs2.SSAFile.from_string(content, keep_html_tags=True)
            except pysubs2.exceptions.FormatError as error:
                errors.append(f"{encoding}: format error - {error}")
        except UnicodeDecodeError as error:
            errors.append(f"{encoding}: {error}")
    details = "\n".join(errors)
    raise ValueError(f"Failed to decode or parse {file_path}:\n{details}")


def load_transcription_words(result_path):
    if not result_path or not os.path.isfile(result_path):
        return []
    try:
        with open(result_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    segments = data.get("segments", []) if isinstance(data, dict) else data
    words = []
    for segment in segments or []:
        for word in segment.get("words", []) or []:
            text = word.get("word", word.get("text", ""))
            if text and word.get("start") is not None and word.get("end") is not None:
                words.append(WordTiming(
                    start=round(float(word["start"]) * 1000),
                    end=round(float(word["end"]) * 1000),
                    text=text,
                ))
    return words


def _normalize_base_events(subs_base, merged):
    normalized = []
    for index, event in enumerate(subs_base):
        style_name = event.style if event.style in merged.styles else "Default"
        style = merged.styles[style_name]
        normalized.append(AlignmentEvent(
            start=event.start,
            end=event.end,
            index=index,
            text=extract_formatting_tags(event.text)[0],
            style=style_name,
            alignment=getattr(style, "alignment", 2),
            positioned=bool(re.search(r'\\(?:pos|move)\(', event.text)),
        ))
    return normalized


def _normalize_secondary_events(second_subs, words=None):
    words = sorted(words or [], key=lambda word: word.start)
    word_starts = [word.start for word in words]
    word_ends = [word.end for word in words]
    normalized = []
    for index, event in enumerate(second_subs):
        first_word = bisect_right(word_ends, event.start)
        last_word = bisect_left(word_starts, event.end)
        normalized.append(AlignmentEvent(
            start=event.start,
            end=event.end,
            index=index,
            text=extract_formatting_tags(event.text)[0],
            style=event.style,
            words=tuple(words[first_word:last_word]),
        ))
    return normalized


def _snap_word_group(words, base_event, match, tolerance):
    start = words[0].start
    end = words[-1].end
    corrected_start = match.transform.apply(start)
    corrected_end = match.transform.apply(end)
    if match.confidence >= 0.5 and abs(corrected_start - base_event.start) <= tolerance:
        start = base_event.start
    if match.confidence >= 0.5 and abs(corrected_end - base_event.end) <= tolerance:
        end = base_event.end
    return (start, end) if end > start else (words[0].start, words[-1].end)


def merge_subtitles(
    base_subs_path,
    second_subs_path,
    transcribed_subs_path,
    output_subs_path,
    detected_language,
    need_romanization=False,
    highlight_current_word=False,
    sync_tolerance=200,
    style_config=None,
    disable_layers=False,
    transcription_result_path=None,
):
    """
    Merge base subtitles with recognized text, creating proper sync.
    
    Args:
        base_subs_path: Path to base subtitles file
        second_subs_path: Path to second subtitles file
        transcribed_subs_path: Path to transcribed subtitles file
        output_subs_path: Path where merged subtitles will be saved
        detected_language: Detected language code
        need_romanization: Whether to add romanization
        highlight_current_word: Whether to highlight current word
        sync_tolerance: Time tolerance for syncing subtitles (in ms)
        style_config: Dictionary with style configurations
    """
    
    subs_base = try_load_subtitles(base_subs_path)
    secondary_subs = transcribed_subs_path if transcribed_subs_path else second_subs_path
    is_transcription = secondary_subs == transcribed_subs_path
    second_subs = try_load_subtitles(secondary_subs)

    task = "transcription text" if is_transcription else "alternative subtitles"
    print(f"[INFO] Merging base subtitles with {task}...")

    converter = None
    if transcribed_subs_path and need_romanization:
        converter = romanization_converter(detected_language)
        print(f"[INFO] Converter loaded for {detected_language} romanization")
           
    merged = initialize_merged_file(subs_base)

    if not is_transcription and second_subs:
        # Copy all styles from second subtitles to preserve formatting
        for style_name, style in second_subs.styles.items():
            merged.styles[style_name] = style

    initialize_default_styles(merged, style_config)
    
    trans_config = style_config.get("transcription", {}) if style_config else {}
    highlight_color = trans_config.get("highlightcolor", None)
    rom_config = style_config.get('romanization', {}) if style_config else {}
    
    second_subs = aggregate_subtitle_lines(second_subs) if not highlight_current_word else [e for e in second_subs if e.text.strip()]
    
    # Process base events
    for base_event in subs_base:
        if base_event.text.strip():
            base_style = base_event.style if base_event.style in merged.styles else "Default"
            merged.append(pysubs2.SSAEvent(
                start=base_event.start,
                end=base_event.end,
                text=base_event.text,
                style=base_style,
                **({"layer": 1} if not disable_layers else {})
            ))
    
    transcription_words = (
        load_transcription_words(transcription_result_path)
        if is_transcription and not highlight_current_word else []
    )
    normalized_base = _normalize_base_events(subs_base, merged)
    normalized_secondary = _normalize_secondary_events(second_subs, transcription_words)
    matches = align_events(normalized_base, normalized_secondary, sync_tolerance)

    # Process secondary events using monotonic, many-to-many alignment.
    for position, sec_event in enumerate(second_subs):
        if not sec_event.text.strip():
            continue

        normalized_event = normalized_secondary[position]
        match = matches.get(position)
        variants = []
        word_groups = split_words_across_bases(
            normalized_event.words,
            match,
            normalized_base,
        )
        if word_groups:
            for base_position, words in word_groups:
                piece_text = "".join(word.text for word in words).strip()
                if not piece_text:
                    continue
                start, end = _snap_word_group(
                    words,
                    normalized_base[base_position],
                    match,
                    sync_tolerance,
                )
                variants.append((piece_text, start, end, base_position))
        else:
            start, end = snap_times(
                normalized_event,
                match,
                normalized_base,
                sync_tolerance,
            )
            base_position = match.primary if match else None
            variants.append((sec_event.text, start, end, base_position))

        for source_text, t_start, t_end, base_position in variants:
            best_match = subs_base[base_position] if base_position is not None else None
            display_text = (
                html_font_to_ass(source_text, highlight_color)
                if highlight_current_word
                else extract_formatting_tags(source_text)[0]
            )
            if not display_text.strip() or t_end <= t_start:
                continue

            n_lines = len(re.findall(r'\\N', best_match.text)) + 1 if best_match else 1
            sec_style = (
                "Transcription"
                if is_transcription
                else (sec_event.style if sec_event.style in merged.styles else "Secondary")
            )
            if best_match:
                style_suffix = f"{sec_style}_{n_lines}"
                base_style_name = best_match.style if best_match.style in merged.styles else "Default"
                adjustment_source = trans_config if is_transcription else {}
                adjusted_config = calculate_adjusted_style_properties(
                    merged.styles[base_style_name],
                    adjustment_source,
                    style_suffix,
                    n_lines,
                )
                sec_style = create_style_if_not_exists(
                    best_match,
                    merged,
                    style_suffix,
                    adjusted_config,
                ) or sec_style

            merged.append(pysubs2.SSAEvent(
                start=t_start,
                end=t_end,
                text=display_text,
                style=sec_style,
                **({"layer": 2} if not disable_layers else {})
            ))

            if need_romanization and converter:
                clean_text, tags_info = extract_formatting_tags(source_text)
                romanized = converter.romanize(clean_text)
                if not romanized or not romanized.strip():
                    continue
                romanized_text = (
                    reapply_formatting_tags(romanized, tags_info)
                    if highlight_current_word else romanized
                )
                romanized_style = "Romanized"
                if best_match:
                    trans_lines = len(re.findall(r'\\N', display_text)) + 1
                    romanized_suffix = f"Romanized_{n_lines}_{trans_lines}"
                    base_style_name = best_match.style if best_match.style in merged.styles else "Default"
                    adjusted_rom_config = calculate_adjusted_style_properties(
                        merged.styles[base_style_name],
                        rom_config,
                        romanized_suffix,
                        n_lines,
                        trans_config,
                        trans_lines,
                    )
                    romanized_style = create_style_if_not_exists(
                        best_match,
                        merged,
                        romanized_suffix,
                        adjusted_rom_config,
                    ) or romanized_style
                merged.append(pysubs2.SSAEvent(
                    start=t_start,
                    end=t_end,
                    text=romanized_text,
                    style=romanized_style,
                    **({"layer": 3} if not disable_layers else {})
                ))

    # Finalize and save the merged subtitles
    merged.sort()
    with atomic_output_path(output_subs_path) as temporary_output:
        merged.save(temporary_output)
