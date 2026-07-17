import argparse
import json
import os
import sys
import time

import pysubs2


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layout import (
    EventRole,
    FallbackTextMeasurer,
    LayoutEvent,
    ObstacleIndex,
    plan_generated_layout,
)


def build_events(count, style):
    events = []
    for index in range(count):
        start = index * 1200
        text = (
            r'{\an8\pos(320,35)}Overlay'
            if index % 11 == 0 else 'Translated dialogue'
        )
        role = EventRole.OVERLAY if index % 11 == 0 else EventRole.DIALOGUE
        events.append(LayoutEvent(
            start=start,
            end=start + 1000,
            text=text,
            style=style,
            role=role,
        ))
    return events


def main():
    parser = argparse.ArgumentParser(description='Benchmark generated subtitle layout')
    parser.add_argument('--events', type=int, default=10000)
    args = parser.parse_args()

    measurer = FallbackTextMeasurer()
    source_style = pysubs2.SSAStyle(fontsize=20, marginv=18, alignment=2)
    transcription_style = pysubs2.SSAStyle(fontsize=16, marginv=30, alignment=2)
    romanization_style = pysubs2.SSAStyle(fontsize=12, marginv=50, alignment=2)
    events = build_events(args.events, source_style)

    started = time.perf_counter()
    obstacles = ObstacleIndex(events, 640, 360, measurer)
    planned = 0
    for event in events:
        plan_generated_layout(
            'Generated dialogue that may wrap on narrow frames',
            transcription_style,
            'Romanized dialogue',
            romanization_style,
            obstacles.query(event.start, event.end),
            640,
            360,
            measurer=measurer,
        )
        planned += 1
    elapsed = time.perf_counter() - started
    print(json.dumps({
        'events': args.events,
        'planned': planned,
        'elapsed_seconds': round(elapsed, 6),
        'events_per_second': round(planned / elapsed, 2) if elapsed else None,
    }, indent=2))


if __name__ == '__main__':
    main()
