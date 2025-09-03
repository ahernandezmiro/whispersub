import subprocess
import re
import pysubs2

from .romanization import romanization_converter
from .utils import file_exists, hex_to_binary

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

    if file_exists(output_subs):
        print(f"[INFO] Subtitle extraction: '{output_subs}' already exists.")
        return output_subs
    

    # mkvextract tracks input.mkv subtitle_track_index:english_subs.srt
    cmd = [
        "mkvextract",
        "tracks",
        input_mkv,
        f"{subtitle_track_index}:{output_subs}"
    ]
    print("[INFO] Extracting subtitles with mkvextract:", " ".join(cmd))
    subprocess.run(cmd, check=True)

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
    text = text.replace('</font>', "{\c}")
    return text

def aggregate_subtitle_lines(subs):
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
            if next_clean != clean_text:
                break
                
            # Extend the aggregated event time
            agg_end = next_event.end
            k += 1
        
        # Create aggregated event
        agg_event = pysubs2.SSAEvent(
            start=agg_start,
            end=agg_end,
            text=rec_event.text  # Keep original text for style preservation
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
    if event and event.style and event.style in merged.styles:
        base_style = merged.styles[event.style].copy()
        style_name = f"{name_suffix}_{event.style}"
        
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
            if str(info_name).lower() == "wrapstyle":
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

    # First attempt: Try UTF-8 with replacement character handling
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            try:
                return pysubs2.SSAFile.from_string(content, keep_html_tags=True)
            except Exception:
                pass  # If this fails, try other approaches
    except Exception:
        pass

    # Read file as binary to examine content
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            
        # Check for UTF-16 BOM
        if raw_data.startswith((b'\xff\xfe', b'\xfe\xff')):
            encoding = 'utf-16le' if raw_data.startswith(b'\xff\xfe') else 'utf-16be'
            try:
                content = raw_data.decode(encoding)
                return pysubs2.SSAFile.from_string(content, keep_html_tags=True)
            except Exception:
                pass

        # Try other encodings with error handlers
        encodings = [
            ('utf-8', 'strict'),
            ('utf-8', 'replace'),
            ('utf-8', 'ignore'),
            ('utf-16le', 'replace'),
            ('utf-16be', 'replace'),
            ('cp1252', 'replace'),
            ('iso-8859-1', 'replace'),
            ('shift_jis', 'replace'),
            ('euc_jp', 'replace'),
            ('cp932', 'replace'),
        ]

        errors = []
        for encoding, error_handler in encodings:
            try:
                content = raw_data.decode(encoding, errors=error_handler)
                try:
                    return pysubs2.SSAFile.from_string(content, keep_html_tags=True)
                except pysubs2.exceptions.FormatError as e:
                    errors.append(f"{encoding} ({error_handler}): Format error - {str(e)}")
                    continue
            except Exception as e:
                errors.append(f"{encoding} ({error_handler}): {str(e)}")
                continue

        error_msg = f"Failed to decode {file_path} with any of the attempted encodings:\n"
        error_msg += "\n".join(errors)
        raise ValueError(error_msg)
            
    except Exception as e:
        raise ValueError(f"Failed to read {file_path}: {str(e)}")
    
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
    disable_layers=False
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
    
    # Process secondary events
    for sec_event in second_subs:
        if not sec_event.text.strip():
            return
            
        text = html_font_to_ass(sec_event.text, highlight_color) if highlight_current_word else extract_formatting_tags(sec_event.text)[0]
        t_start = sec_event.start
        t_end = sec_event.end

        # Find matching base event(s) based on time overlap
        matching_base_events = [
            e for e in subs_base 
            if (sec_event.start <= e.end and sec_event.end >= e.start)
        ]
        
        n_lines = 1
        sec_style = "Transcription" if is_transcription else (sec_event.style if sec_event.style in merged.styles else "Secondary")
        best_match = None

        if matching_base_events:
            ''' TODO: process all matching events, not just best match.
             update start and end times in the current approach, generating various subtitles if applicable
             adjust style for each segment to its related matching event one
            '''
            # Find the best matching base event
            best_match = min(matching_base_events, key=lambda e: 
                abs(e.start - sec_event.start) + abs(e.end - sec_event.end))
            
            n_lines = len(re.findall(r'\\N', best_match.text)) + 1 
            sec_style = f"{sec_style}_{n_lines}"
            if is_transcription:
                # Calculate style properties with adjustments for n_lines
                style_config = calculate_adjusted_style_properties(
                    merged.styles[best_match.style],
                    trans_config,
                    sec_style,
                    n_lines
                )

                # Create style with adjusted properties
                sec_style = create_style_if_not_exists(best_match, merged, sec_style, style_config)
            else:
                # Calculate style properties with adjustments for n_lines
                sec_config = calculate_adjusted_style_properties(
                    merged.styles[best_match.style],
                    {},
                    sec_style,
                    n_lines
                )
                sec_style = create_style_if_not_exists(best_match, merged, sec_style, sec_config)

            # Snap to base event times if within tolerance
            if abs(sec_event.start - best_match.start) <= sync_tolerance:
                t_start = best_match.start
            if abs(sec_event.end - best_match.end) <= sync_tolerance:
                if(t_start < best_match.start - sync_tolerance):
                    t_start = best_match.start + 1
                    alt_event = pysubs2.SSAEvent(
                        start=sec_event.start,
                        end=best_match.start,
                        text=text,
                        style=sec_style,
                        **({"layer": 2} if not disable_layers else {})
                    )
                t_end = best_match.end
    
        # Add the main secondary event
        alt_event = pysubs2.SSAEvent(
            start=t_start,
            end=t_end,
            text=text,
            style=sec_style,
            **({"layer": 2} if not disable_layers else {})
        )
        merged.append(alt_event)

        # Process romanization if needed
        if need_romanization and converter:
            clean_text, tags_info = extract_formatting_tags(sec_event.text)
            romanized = converter.romanize(clean_text)
            if romanized.strip():
                romanized_text = reapply_formatting_tags(romanized, tags_info) if highlight_current_word else romanized

                romanized_style = "Romanized"
                if best_match:
                    trans_lines = len(re.findall(r'\\N', sec_event.text)) + 1 # TODO: also account for ASS auto line wrapping
                    romanized_style = f"Romanized_{n_lines}_{trans_lines}"

                    # Calculate style properties with adjustments for n_lines
                    adjusted_rom_config = calculate_adjusted_style_properties(
                        merged.styles[best_match.style],
                        rom_config,
                        romanized_style,
                        n_lines,
                        trans_config,
                        trans_lines
                    )
                    romanized_style = create_style_if_not_exists(best_match, merged, romanized_style, adjusted_rom_config)

                romanized_event = pysubs2.SSAEvent(
                    start=t_start,
                    end=t_end,
                    text=romanized_text,
                    style=romanized_style,
                    **({"layer": 3} if not disable_layers else {})
                )
                merged.append(romanized_event)

    # Finalize and save the merged subtitles
    merged.sort()
    merged.save(output_subs_path)
