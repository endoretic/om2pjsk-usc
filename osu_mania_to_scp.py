#!/usr/bin/env python3
"""osu!mania → USC → SCP converter CLI.

Usage:
    python osu_mania_to_scp.py <input.osz> [--engine engine.scp] [--out output.scp]
    python osu_mania_to_scp.py <input.osz> --dump-usc <dir>
    python osu_mania_to_scp.py <input.osz> --list
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

from src.osu_parser import OsuChart, parse_osu
from src.osu_to_usc import osu_to_usc, osu_to_usc_json


def read_osz(path: str) -> "OrderedDict[str, bytes]":
    """Read a .osz (ZIP) file, returning entries keyed by path."""
    entries: "OrderedDict[str, bytes]" = OrderedDict()
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            entries[name] = zf.read(info)
    return entries


def decode_osu_text(data: bytes) -> str:
    """Decode .osu file content with encoding fallback."""
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def parse_all_charts(entries: Dict[str, bytes]) -> List[OsuChart]:
    """Parse all mania .osu files in the archive."""
    charts: List[OsuChart] = []
    for path, data in entries.items():
        if not path.endswith(".osu"):
            continue
        text = decode_osu_text(data)
        chart = parse_osu(text)
        if chart.is_mania:
            charts.append(chart)
    return charts


def filter_valid_charts(charts: List[OsuChart]) -> List[OsuChart]:
    """Filter out placeholder/empty charts."""
    return [c for c in charts if not c.is_placeholder and c.key_count > 0]


def summarize_chart(chart: OsuChart) -> Dict:
    """Return a summary dict for a parsed chart."""
    return {
        "title": chart.title,
        "artist": chart.artist,
        "version": chart.version,
        "creator": chart.creator,
        "key_count": chart.key_count,
        "hit_objects": len(chart.hit_objects),
        "timing_points": len(chart.timing_points),
        "audio": chart.audio_filename,
        "background": chart.background_filename,
        "first_red_time_ms": chart.first_red_time,
    }


def cmd_list(entries: Dict[str, bytes]) -> int:
    """List all mania charts in the .osz."""
    charts = parse_all_charts(entries)
    valid = filter_valid_charts(charts)
    print(f"Found {len(valid)} valid mania chart(s):\n")
    for i, c in enumerate(valid):
        s = summarize_chart(c)
        print(f"  {i+1}. [{s['key_count']}K] {s['title']} — {s['version']}")
        print(f"     Artist: {s['artist']} | Creator: {s['creator']}")
        print(f"     Notes: {s['hit_objects']} | Timing: {s['timing_points']}")
        print(f"     Audio: {s['audio']} | BG: {s['background']}")
        print()
    return 0


def cmd_dump_usc(entries: Dict[str, bytes], out_dir: str, single_version: Optional[str] = None) -> int:
    """Dump USC JSON for one or all charts."""
    charts = parse_all_charts(entries)
    valid = filter_valid_charts(charts)
    if not valid:
        print("No valid mania charts found.", file=sys.stderr)
        return 1

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    targets = valid
    if single_version:
        targets = [c for c in valid if c.version == single_version]
        if not targets:
            print(f"Chart version '{single_version}' not found. Available:",
                  file=sys.stderr)
            for c in valid:
                print(f"  {c.version}", file=sys.stderr)
            return 1

    for chart in targets:
        usc_json = osu_to_usc_json(chart)
        safe_name = chart.version.replace("/", "_").replace("\\", "_")
        filename = out_path / f"{safe_name}.usc.json"
        filename.write_text(usc_json, encoding="utf-8")
        print(f"Wrote: {filename}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert osu!mania .osz beatmaps to USC JSON or SCP packages.",
    )
    parser.add_argument("input", help="Path to .osz file")
    parser.add_argument("--list", action="store_true", help="List all mania charts in the .osz")
    parser.add_argument("--dump-usc", metavar="DIR", help="Dump USC JSON to directory")
    parser.add_argument("--single-difficulty", metavar="VERSION",
                        help="Process only the specified difficulty version name")
    parser.add_argument("--engine", metavar="SCP", help="Path to engine.scp resource pack")
    parser.add_argument("--out", metavar="SCP", help="Output .scp file path")

    args = parser.parse_args(argv)

    if not Path(args.input).exists():
        print(f"File not found: {args.input}", file=sys.stderr)
        return 1

    entries = read_osz(args.input)

    if args.list:
        return cmd_list(entries)

    if args.dump_usc:
        return cmd_dump_usc(entries, args.dump_usc, args.single_difficulty)

    if args.out:
        if not args.engine:
            print("--engine is required when using --out", file=sys.stderr)
            return 1
        from src.scp_writer import build_scp
        return build_scp(args.input, args.engine, args.out, args.single_difficulty)

    # Default: list what's available
    print("Use --list to see available charts, --dump-usc to generate USC JSON,")
    print("or --engine/--out to build a .scp package.\n")
    return cmd_list(entries)


if __name__ == "__main__":
    sys.exit(main())
