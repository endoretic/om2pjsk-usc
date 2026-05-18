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
from src.osu_to_usc import TAIL_MODES, osu_to_usc_json


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


def cmd_dump_usc(
    entries: Dict[str, bytes],
    out_dir: str,
    single_version: Optional[str] = None,
    tail_mode: str = "release",
) -> int:
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
        usc_json = osu_to_usc_json(chart, tail_mode=tail_mode)
        safe_name = chart.version.replace("/", "_").replace("\\", "_")
        filename = out_path / f"{safe_name}.usc.json"
        filename.write_text(usc_json, encoding="utf-8")
        print(f"Wrote: {filename}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert osu!mania .osz beatmaps to USC JSON or SCP packages.",
    )
    parser.add_argument("input", nargs="+", help="Path to one or more .osz files")
    parser.add_argument("--list", action="store_true", help="List all mania charts in the .osz")
    parser.add_argument("--dump-usc", metavar="DIR", help="Dump USC JSON to directory")
    parser.add_argument("--single-difficulty", metavar="VERSION",
                        help="Process only the specified difficulty version name")
    parser.add_argument("--engine", metavar="SCP", help="Path to engine.scp resource pack")
    parser.add_argument("--out", metavar="SCP", help="Output .scp file path")
    parser.add_argument("--out-dir", metavar="DIR",
                        help="Output directory for one .scp per input when multiple inputs are provided")
    parser.add_argument("--merge", action="store_true",
                        help="Merge all input .osz packages into one output .scp")
    parser.add_argument("--tail-mode", choices=sorted(TAIL_MODES), default="release",
                        help="Hold tail style for converted slide endings")
    parser.add_argument("--background-mode", choices=("default", "original"), default="default",
                        help="Use NextRUSH+ default gameplay background or generated original osu backgrounds")

    args = parser.parse_args(argv)

    for input_path in args.input:
        if not Path(input_path).exists():
            print(f"File not found: {input_path}", file=sys.stderr)
            return 1

    if args.list:
        status = 0
        for input_path in args.input:
            print(f"\n== {input_path} ==")
            status |= cmd_list(read_osz(input_path))
        return status

    if args.dump_usc:
        if len(args.input) != 1:
            print("--dump-usc currently accepts exactly one input .osz", file=sys.stderr)
            return 1
        entries = read_osz(args.input[0])
        return cmd_dump_usc(entries, args.dump_usc, args.single_difficulty, args.tail_mode)

    if args.out or args.out_dir:
        if not args.engine:
            print("--engine is required when writing .scp output", file=sys.stderr)
            return 1
        from src.scp_writer import build_merged_scp, build_scp

        if args.merge:
            if not args.out:
                print("--out is required with --merge", file=sys.stderr)
                return 1
            return build_merged_scp(
                args.input,
                args.engine,
                args.out,
                single_version=args.single_difficulty,
                tail_mode=args.tail_mode,
                background_mode=args.background_mode,
            )

        if len(args.input) == 1:
            if not args.out:
                print("--out is required for a single input conversion", file=sys.stderr)
                return 1
            return build_scp(
                args.input[0],
                args.engine,
                args.out,
                args.single_difficulty,
                tail_mode=args.tail_mode,
                background_mode=args.background_mode,
            )

        if not args.out_dir:
            print("--out-dir is required for multiple one-to-one conversions", file=sys.stderr)
            return 1
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        status = 0
        for input_path in args.input:
            output_path = out_dir / f"{Path(input_path).stem}.scp"
            status |= build_scp(
                input_path,
                args.engine,
                str(output_path),
                args.single_difficulty,
                tail_mode=args.tail_mode,
                background_mode=args.background_mode,
            )
        return status

    # Default: list what's available
    print("Use --list to see available charts, --dump-usc to generate USC JSON,")
    print("or --engine/--out to build a .scp package.\n")
    return cmd_list(read_osz(args.input[0]))


if __name__ == "__main__":
    sys.exit(main())
