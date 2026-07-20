import subprocess
import re
import json
import os
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import pysubs2

from .alignment import (
    AlignmentEvent,
    SnapProposal,
    WordTiming,
    align_events,
    propose_snap_times,
    resolve_snapped_spans,
    split_words_across_bases,
)
from .cache import atomic_output_path, build_manifest, cache_is_valid, write_manifest
from .layout import (
    EventRole,
    FallbackTextMeasurer,
    LayoutEvent,
    ObstacleIndex,
    classify_event_role,
    plan_generated_layout,
)
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

def _resolve_relative_value(value, base_value, property_name):
    if value is None:
        return base_value
    try:
        if isinstance(value, str):
            if value.startswith('*'):
                return base_value * float(value[1:])
            if value.startswith('+'):
                return base_value + float(value[1:])
            if value.startswith('-'):
                return base_value - float(value[1:])
        return float(value)
    except (TypeError, ValueError):
        print(f'[WARNING] Invalid {property_name} value: {value}. Using {base_value}.')
        return base_value


def _generated_style_name(base_name, zone, alignment, marginv, fontsize):
    size_key = f'{fontsize:.2f}'.rstrip('0').rstrip('.').replace('.', 'p')
    return f'{base_name}_{zone}_an{alignment}_m{marginv}_s{size_key}'


def _ensure_generated_style(merged, base_name, zone, alignment, marginv, fontsize):
    style_name = _generated_style_name(
        base_name, zone, alignment, marginv, fontsize
    )
    if style_name not in merged.styles:
        style = merged.styles[base_name].copy()
        style.alignment = pysubs2.Alignment(alignment)
        style.marginv = marginv
        style.fontsize = fontsize
        merged.styles[style_name] = style
    return style_name


def _available_generated_base_name(merged, preferred):
    if preferred not in merged.styles:
        return preferred
    stem = f'WhisperSub_{preferred}'
    candidate = stem
    suffix = 2
    while candidate in merged.styles:
        candidate = f'{stem}_{suffix}'
        suffix += 1
    return candidate

def initialize_merged_file(subs_base=None):
    merged = pysubs2.SSAFile()
    
    if subs_base:
        # Copy all styles from base subtitles to preserve formatting
        for style_name, style in subs_base.styles.items():
            merged.styles[style_name] = style.copy()

        for info_name, info in subs_base.info.items():
            if str(info_name).lower() == "collisions":
                merged.info[info_name] = "Normal"
            elif str(info_name).lower() == "wrapstyle":
                merged.info[info_name] = 3
            else:
                merged.info[info_name] = info
                
    return merged

def initialize_default_styles(merged, style_config=None):
    trans_style_name = _available_generated_base_name(merged, 'Transcription')
    rom_style_name = _available_generated_base_name(merged, 'Romanized')
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
        
    if trans_style_name not in merged.styles:
        font_size = _resolve_relative_value(
            trans_config.get('fontsize'), 16, 'transcription font size'
        )
        marginv = _resolve_relative_value(
            trans_config.get('marginv'), 30, 'transcription margin'
        )
        merged.styles[trans_style_name] = pysubs2.SSAStyle(
            fontname=trans_config.get('fontname', 'Arial'),
            fontsize=font_size,
            bold=trans_config.get('bold', False),
            italic=trans_config.get('italic', False),
            underline=False,
            strikeout=False,
            outline=1,
            shadow=1,
            marginv=marginv,
            alignment=2,
            primarycolor=hex_to_binary(trans_config.get('primarycolor', 'FFFFFF')),
            secondarycolor=hex_to_binary(trans_config.get('secondarycolor', 'FFFFFF')),
            outlinecolor=hex_to_binary("000000"),
            backcolor=hex_to_binary("000000"),
            borderstyle=1,
            scalex=100,
            scaley=100
        )
    if rom_style_name not in merged.styles:
        font_size = _resolve_relative_value(
            rom_config.get('fontsize'), 12, 'romanization font size'
        )
        marginv = _resolve_relative_value(
            rom_config.get('marginv'), 50, 'romanization margin'
        )
        merged.styles[rom_style_name] = pysubs2.SSAStyle(
            fontname=rom_config.get('fontname', 'Arial'),
            fontsize=font_size,
            bold=rom_config.get('bold', False),
            italic=rom_config.get('italic', True),
            underline=False,
            strikeout=False,
            outline=1,
            shadow=1,
            marginv=marginv,
            alignment=2,
            primarycolor=hex_to_binary(rom_config.get('primarycolor', 'BCBCBC')),
            secondarycolor=hex_to_binary(rom_config.get('secondarycolor', 'BCBCBC')),
            outlinecolor=hex_to_binary("000000"),
            backcolor=hex_to_binary("000000"),
            borderstyle=1,
            scalex=100,
            scaley=100
        )

    return trans_style_name, rom_style_name


def _normalize_newlines(content):
    return content.replace('\r\n', '\n').replace('\r', '\n')


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
            content = _normalize_newlines(content)
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
        positioned = (
            bool(re.search(r'\\(?:pos|move)\(', event.text))
            or getattr(event, 'is_comment', False)
        )
        alignment_tag = re.search(r'\\an([1-9])', event.text)
        alignment = (
            int(alignment_tag.group(1))
            if alignment_tag else getattr(style, 'alignment', 2)
        )
        role = classify_event_role(
            event.text,
            style_name,
            alignment,
            positioned,
            getattr(event, 'effect', ''),
        )
        normalized.append(AlignmentEvent(
            start=event.start,
            end=event.end,
            index=index,
            text=extract_formatting_tags(event.text)[0],
            style=style_name,
            alignment=alignment,
            positioned=positioned,
            role=role.value,
        ))
    return normalized


def _script_resolution(merged):
    def parse(name, default):
        try:
            return max(1, int(float(merged.info.get(name, default))))
        except (TypeError, ValueError):
            return default

    return parse('PlayResX', 384), parse('PlayResY', 288)


def _layout_events(subs_base, merged, normalized_base):
    events = []
    for event, normalized in zip(subs_base, normalized_base):
        if not event.text.strip() or getattr(event, 'is_comment', False):
            continue
        style_name = event.style if event.style in merged.styles else 'Default'
        events.append(LayoutEvent(
            start=event.start,
            end=event.end,
            text=event.text,
            style=merged.styles[style_name],
            role=EventRole(normalized.role),
            layer=getattr(event, 'layer', 0),
            marginl=getattr(event, 'marginl', 0),
            marginr=getattr(event, 'marginr', 0),
            marginv=getattr(event, 'marginv', 0),
        ))
    return events


def _layout_anchor(match, normalized_base):
    if not match or match.confidence < 0.5:
        return None
    eligible = [
        position for position in match.bases
        if normalized_base[position].role == EventRole.DIALOGUE.value
    ]
    if not eligible:
        return None
    return match.primary if match.primary in eligible else eligible[0]


@dataclass(frozen=True)
class _RenderGroup:
    text: str
    members: tuple

    @property
    def start(self):
        return self.members[0].start

    @property
    def end(self):
        return self.members[-1].end


def _group_secondary_events(second_subs, group_highlight_frames, max_gap=1000):
    groups = []
    for event in second_subs:
        if not event.text.strip():
            continue
        clean_text = extract_formatting_tags(event.text)[0]
        if (
            group_highlight_frames
            and groups
            and groups[-1].text == clean_text
            and event.start - groups[-1].end <= max_gap
        ):
            previous = groups[-1]
            groups[-1] = _RenderGroup(
                text=previous.text,
                members=previous.members + (event,),
            )
        else:
            groups.append(_RenderGroup(clean_text, (event,)))
    return groups


def _normalize_secondary_events(groups, words=None):
    words = sorted(words or [], key=lambda word: word.start)
    word_starts = [word.start for word in words]
    word_ends = [word.end for word in words]
    normalized = []
    for index, group in enumerate(groups):
        first_word = bisect_right(word_ends, group.start)
        last_word = bisect_left(word_starts, group.end)
        normalized.append(AlignmentEvent(
            start=group.start,
            end=group.end,
            index=index,
            text=group.text,
            style=group.members[0].style,
            words=tuple(words[first_word:last_word]),
        ))
    return normalized


def _render_group_variants(
    group,
    normalized_event,
    match,
    normalized_base,
    resolved_span,
):
    variants = []
    word_groups = split_words_across_bases(
        normalized_event.words,
        match,
        normalized_base,
    )
    if word_groups:
        for base_position, words in word_groups:
            piece_text = "".join(word.text for word in words).strip()
            if piece_text:
                variants.append([
                    piece_text, words[0].start, words[-1].end, base_position
                ])
    else:
        base_position = match.primary if match else None
        for member in group.members:
            variants.append([
                member.text, member.start, member.end, base_position
            ])

    if variants:
        variants[0][1] = resolved_span[0]
        variants[-1][2] = resolved_span[1]
    return [tuple(variant) for variant in variants]


def _constrain_group_proposal(group, normalized_event, proposal):
    """Reject outer snaps that would erase the first or last rendered member."""
    first_end = group.members[0].end
    last_start = group.members[-1].start
    if len(group.members) == 1 and normalized_event.words:
        first_end = normalized_event.words[0].end
        last_start = normalized_event.words[-1].start
    start = proposal.start
    end = proposal.end
    if start is not None and start >= first_end:
        start = None
    if end is not None and end <= last_start:
        end = None
    return SnapProposal(start=start, end=end)


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

    secondary_style_map = {}
    if not is_transcription and second_subs:
        # Preserve both definitions when independent source tracks reuse a name.
        for style_name, style in second_subs.styles.items():
            target_name = style_name
            if (
                target_name in merged.styles
                and merged.styles[target_name] != style
            ):
                stem = f'Secondary_{style_name}'
                target_name = stem
                suffix = 2
                while target_name in merged.styles:
                    target_name = f'{stem}_{suffix}'
                    suffix += 1
            if target_name not in merged.styles:
                merged.styles[target_name] = style.copy()
            secondary_style_map[style_name] = target_name

    trans_style_name, rom_style_name = initialize_default_styles(
        merged, style_config
    )
    
    trans_config = style_config.get("transcription", {}) if style_config else {}
    highlight_color = trans_config.get("highlightcolor", None)
    if is_transcription:
        second_subs = (
            aggregate_subtitle_lines(second_subs)
            if not highlight_current_word
            else [event for event in second_subs if event.text.strip()]
        )
    
    # Process base events
    for base_event in subs_base:
        base_style = base_event.style if base_event.style in merged.styles else "Default"
        rendered_base = base_event.copy()
        rendered_base.style = base_style
        if not disable_layers:
            rendered_base.layer = 1
        merged.append(rendered_base)
    
    transcription_words = (
        load_transcription_words(transcription_result_path)
        if is_transcription and not highlight_current_word else []
    )
    render_groups = _group_secondary_events(
        second_subs,
        group_highlight_frames=is_transcription and highlight_current_word,
    )
    normalized_base = _normalize_base_events(subs_base, merged)
    normalized_secondary = _normalize_secondary_events(
        render_groups, transcription_words
    )
    matches = align_events(normalized_base, normalized_secondary, sync_tolerance)
    proposals = [
        _constrain_group_proposal(
            render_groups[position],
            event,
            propose_snap_times(
                event,
                matches.get(position),
                normalized_base,
                sync_tolerance,
            ),
        )
        for position, event in enumerate(normalized_secondary)
    ]
    resolved_spans = resolve_snapped_spans(
        [(event.start, event.end) for event in normalized_secondary],
        proposals,
    )

    play_res_x = play_res_y = None
    text_measurer = obstacle_index = None
    if is_transcription:
        play_res_x, play_res_y = _script_resolution(merged)
        text_measurer = FallbackTextMeasurer()
        obstacle_index = ObstacleIndex(
            _layout_events(subs_base, merged, normalized_base),
            play_res_x,
            play_res_y,
            text_measurer,
        )
    else:
        for event in second_subs:
            if event.text.strip():
                continue
            rendered_secondary = event.copy()
            rendered_secondary.style = secondary_style_map.get(
                event.style, 'Secondary'
            )
            if not disable_layers:
                rendered_secondary.layer = 2
            merged.append(rendered_secondary)

    # Process ordered utterance groups using their resolved outer envelopes.
    for position, group in enumerate(render_groups):
        normalized_event = normalized_secondary[position]
        match = matches.get(position)
        variants = _render_group_variants(
            group,
            normalized_event,
            match,
            normalized_base,
            resolved_spans[position],
        )
        if not variants:
            continue

        if is_transcription:
            utterance_text = group.text
            utterance_romanized = None
            if need_romanization and converter:
                utterance_romanized = converter.romanize(utterance_text)
                if not utterance_romanized or not utterance_romanized.strip():
                    utterance_romanized = None

            anchor_position = _layout_anchor(match, normalized_base)
            preferred_zone = 'bottom'
            if (
                anchor_position is not None
                and normalized_base[anchor_position].alignment in (7, 8, 9)
            ):
                preferred_zone = 'top'
            layout_start, layout_end = resolved_spans[position]
            layout_plan = plan_generated_layout(
                utterance_text,
                merged.styles[trans_style_name],
                utterance_romanized,
                merged.styles[rom_style_name],
                obstacle_index.query(layout_start, layout_end),
                play_res_x,
                play_res_y,
                preferred_zone=preferred_zone,
                measurer=text_measurer,
            )
            sec_style = _ensure_generated_style(
                merged,
                trans_style_name,
                layout_plan.zone,
                layout_plan.alignment,
                layout_plan.transcription_marginv,
                layout_plan.transcription_fontsize,
            )
            romanized_style = None
            if utterance_romanized:
                romanized_style = _ensure_generated_style(
                    merged,
                    rom_style_name,
                    layout_plan.zone,
                    layout_plan.alignment,
                    layout_plan.romanization_marginv,
                    layout_plan.romanization_fontsize,
                )
        else:
            source_event = group.members[0]
            sec_style = secondary_style_map.get(
                source_event.style, 'Secondary'
            )
            romanized_style = None

        for source_text, t_start, t_end, _ in variants:
            display_text = (
                html_font_to_ass(source_text, highlight_color)
                if highlight_current_word
                else extract_formatting_tags(source_text)[0]
            )
            if not display_text.strip() or t_end <= t_start:
                continue

            if is_transcription:
                rendered_secondary = pysubs2.SSAEvent(
                    start=t_start,
                    end=t_end,
                    text=display_text,
                    style=sec_style,
                    **({'layer': 2} if not disable_layers else {})
                )
            else:
                rendered_secondary = source_event.copy()
                rendered_secondary.start = t_start
                rendered_secondary.end = t_end
                rendered_secondary.text = display_text
                rendered_secondary.style = sec_style
                if not disable_layers:
                    rendered_secondary.layer = 2
            merged.append(rendered_secondary)

            if romanized_style and converter:
                clean_text, tags_info = extract_formatting_tags(source_text)
                romanized = converter.romanize(clean_text)
                if not romanized or not romanized.strip():
                    continue
                romanized_text = (
                    reapply_formatting_tags(romanized, tags_info)
                    if highlight_current_word else romanized
                )
                merged.append(pysubs2.SSAEvent(
                    start=t_start,
                    end=t_end,
                    text=romanized_text,
                    style=romanized_style,
                    **({'layer': 3} if not disable_layers else {})
                ))

    # Finalize and save the merged subtitles
    merged.sort()
    with atomic_output_path(output_subs_path) as temporary_output:
        merged.save(temporary_output)
