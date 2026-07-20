"""Render selected ASS frames with ffmpeg/libass for optional visual QA."""

import argparse
import os
import shutil
import subprocess


def _filter_path(path):
    normalized = os.path.abspath(path).replace('\\', '/')
    return normalized.replace(':', r'\:').replace("'", r"\'")


def render_frames(subtitle_path, output_directory, timestamps, size):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError(
            'ffmpeg with the subtitles/libass filter is required for this '
            'optional developer check'
        )
    if not os.path.isfile(subtitle_path):
        raise ValueError(f'Subtitle file does not exist: {subtitle_path}')

    os.makedirs(output_directory, exist_ok=True)
    subtitle_filter = f"ass=filename='{_filter_path(subtitle_path)}'"
    outputs = []
    for index, timestamp in enumerate(timestamps, start=1):
        if timestamp < 0:
            raise ValueError('Timestamps must be non-negative')
        output_path = os.path.join(
            output_directory,
            f'frame-{index:02d}-{timestamp:.3f}s.png',
        )
        command = [
            ffmpeg,
            '-hide_banner',
            '-loglevel',
            'error',
            '-y',
            '-f',
            'lavfi',
            '-i',
            f'color=c=black:s={size}:r=1:d={timestamp + 1}',
            '-vf',
            subtitle_filter,
            '-ss',
            str(timestamp),
            '-frames:v',
            '1',
            output_path,
        ]
        subprocess.run(command, check=True)
        outputs.append(output_path)
    return outputs


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Render one or more frames from an ASS file against a black '
            'background for optional layout comparison.'
        )
    )
    parser.add_argument('subtitle_file', help='ASS subtitle file to render')
    parser.add_argument(
        '--timestamp',
        dest='timestamps',
        type=float,
        action='append',
        required=True,
        help='Frame timestamp in seconds; repeat for multiple frames',
    )
    parser.add_argument(
        '--output-dir',
        default=os.path.join('.tmp', 'render-fixture'),
        help='Directory for rendered PNG files',
    )
    parser.add_argument(
        '--size',
        default='1280x720',
        help='Render size understood by ffmpeg, such as 1280x720',
    )
    arguments = parser.parse_args()
    for output in render_frames(
        arguments.subtitle_file,
        arguments.output_dir,
        arguments.timestamps,
        arguments.size,
    ):
        print(output)


if __name__ == '__main__':
    main()
