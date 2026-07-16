#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.alignment import AlignmentEvent, align_events


def build_events(count, offset):
    base = []
    secondary = []
    for index in range(count):
        start = index * 2500
        base.append(AlignmentEvent(start, start + 1800, index, text=f"base {index}"))
        secondary.append(AlignmentEvent(
            start + offset,
            start + 1750 + offset,
            index,
            text=f"secondary {index}",
        ))
    return base, secondary


def main():
    parser = argparse.ArgumentParser(description="Benchmark WhisperSub subtitle alignment.")
    parser.add_argument("--events", type=int, default=5000)
    parser.add_argument("--offset", type=int, default=120)
    parser.add_argument("--tolerance", type=int, default=200)
    args = parser.parse_args()

    base, secondary = build_events(args.events, args.offset)
    started = time.perf_counter()
    matches = align_events(base, secondary, args.tolerance)
    elapsed = time.perf_counter() - started
    print(json.dumps({
        "base_events": len(base),
        "secondary_events": len(secondary),
        "matches": len(matches),
        "elapsed_seconds": round(elapsed, 6),
        "events_per_second": round(len(secondary) / elapsed, 2),
    }, indent=2))


if __name__ == "__main__":
    main()
