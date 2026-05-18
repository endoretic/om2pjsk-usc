"""SCP package writer.

Assembles Sonolus .scp packages from:
- Parsed osu!mania charts
- Engine resource pack (engine.scp)
- Generated LevelData blobs
- BGM and cover assets from the .osz
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .osu_parser import OsuChart
from .osu_to_usc import osu_to_usc
from .nextrush_leveldata import (
    leveldata_blob,
    serialize_leveldata,
    sha1_hex,
    usc_to_leveldata,
)


def _read_zip_entries(path: str) -> "OrderedDict[str, bytes]":
    """Read all entries from a ZIP file (normalizes paths to forward slash)."""
    entries: "OrderedDict[str, bytes]" = OrderedDict()
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            entries[name] = zf.read(info)
    return entries


def _write_zip(path: str, entries: "OrderedDict[str, bytes]") -> None:
    """Write entries to a ZIP file with maximum compression."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


# ---------------------------------------------------------------------------
# Sonolus metadata helpers
# ---------------------------------------------------------------------------

_RESOURCE_CATEGORIES = ["skins", "backgrounds", "effects", "particles"]
_ENGINE_CATEGORY = "engines"
_LEVEL_CATEGORY = "levels"


def _iter_repo_paths(obj: Any) -> List[str]:
    """Recursively find all /sonolus/repository/<hash> references in a JSON object."""
    paths: List[str] = []
    if isinstance(obj, dict):
        url = obj.get("url")
        if isinstance(url, str) and url.startswith("/sonolus/repository/"):
            paths.append(url.lstrip("/"))
        for v in obj.values():
            paths.extend(_iter_repo_paths(v))
    elif isinstance(obj, list):
        for v in obj:
            paths.extend(_iter_repo_paths(v))
    return paths


def _json_load_safe(entries: Dict[str, bytes], path: str) -> Any:
    """Load and parse JSON from an entry, returning None on failure."""
    data = entries.get(path)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _json_dump(obj: Any) -> bytes:
    """Serialize to compact JSON bytes."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _category_item_paths(entries: Dict[str, bytes], category: str) -> List[str]:
    """Get all item paths for a category (excluding list and info)."""
    prefix = f"sonolus/{category}/"
    skip = {f"sonolus/{category}/list", f"sonolus/{category}/info"}
    return [p for p in entries if p.startswith(prefix) and p not in skip]


def _repository_entries(entries: Dict[str, bytes]) -> Set[str]:
    """Get all repository blob paths."""
    return {p for p in entries if p.startswith("sonolus/repository/")}


# ---------------------------------------------------------------------------
# Level item builder
# ---------------------------------------------------------------------------

def _build_level_item(
    chart: OsuChart,
    engine_item: Dict[str, Any],
    leveldata_hash: str,
    bgm_hash: str,
    cover_hash: str,
) -> Dict[str, Any]:
    """Build a Sonolus level item from a parsed chart."""
    base_name = chart.title
    if chart.artist:
        base_name = f"{chart.artist} - {base_name}"

    title = base_name
    if chart.version:
        title = f"{base_name} [{chart.version}]"

    return {
        "name": f"om2usc-{chart.version.replace(' ', '-').replace('/', '-')}",
        "version": 1,
        "title": title,
        "artists": chart.artist,
        "author": chart.creator,
        "rating": 0,
        "tags": [],
        "description": f"Converted from osu!mania ({chart.key_count}K)",
        "engine": copy.deepcopy(engine_item),
        "useSkin": {"useDefault": True},
        "useBackground": {"useDefault": True},
        "useEffect": {"useDefault": True},
        "useParticle": {"useDefault": True},
        "bgm": {
            "hash": bgm_hash,
            "url": f"/sonolus/repository/{bgm_hash}",
        },
        "cover": {
            "hash": cover_hash,
            "url": f"/sonolus/repository/{cover_hash}",
        },
        "data": {
            "hash": leveldata_hash,
            "url": f"/sonolus/repository/{leveldata_hash}",
        },
    }


# ---------------------------------------------------------------------------
# Main SCP builder
# ---------------------------------------------------------------------------

def build_scp(
    osz_path: str,
    engine_path: str,
    output_path: str,
    single_version: Optional[str] = None,
    include_all: bool = True,
) -> int:
    """Build a complete .scp package from .osz + engine.scp.

    Returns 0 on success, 1 on error.
    """
    from .osu_parser import parse_osu as _parse_osu

    # --- Read inputs ---
    osz_entries = _read_zip_entries(osz_path)
    engine_entries = _read_zip_entries(engine_path)

    # --- Parse .osu files ---
    osu_charts: List[Tuple[str, OsuChart]] = []
    for path, data in osz_entries.items():
        if not path.endswith(".osu"):
            continue
        text = _decode_osu(data)
        chart = _parse_osu(text)
        if chart.is_mania and not chart.is_placeholder and chart.key_count > 0:
            if single_version and chart.version != single_version:
                continue
            osu_charts.append((path, chart))

    if not osu_charts:
        print("No valid mania charts found.", __import__("sys").stderr)
        return 1

    print(f"Found {len(osu_charts)} valid chart(s)")

    # --- Extract engine item ---
    engine_item_path = f"sonolus/engines/NextRUSH_P"
    engine_doc = _json_load_safe(engine_entries, engine_item_path)
    if not engine_doc:
        print(f"Engine not found in {engine_path}", __import__("sys").stderr)
        return 1
    engine_item = engine_doc.get("item", engine_doc) if isinstance(engine_doc, dict) else engine_doc

    # --- Build output entries ---
    out: "OrderedDict[str, bytes]" = OrderedDict()

    # Copy engine resources (lists, infos, items, repository blobs)
    _copy_engine_resources(out, engine_entries)

    # Collect level list items
    level_items: List[Dict[str, Any]] = []

    for osu_path, chart in osu_charts:
        print(f"  Processing: {chart.version} ({chart.key_count}K, {len(chart.hit_objects)} notes)")

        # --- Convert to LevelData ---
        usc = osu_to_usc(chart)
        leveldata = usc_to_leveldata(usc)
        ld_blob, ld_hash = leveldata_blob(leveldata)

        # Store LevelData in repository
        ld_repo_path = f"sonolus/repository/{ld_hash}"
        if ld_repo_path not in out:
            out[ld_repo_path] = ld_blob

        # --- Copy BGM ---
        bgm_data = _find_asset(osz_entries, chart.audio_filename)
        if bgm_data is None:
            print(f"    WARNING: BGM '{chart.audio_filename}' not found in .osz",
                  __import__("sys").stderr)
        bgm_blob = gzip.compress(bgm_data or b"", mtime=0)
        bgm_hash = sha1_hex(bgm_blob)
        bgm_repo_path = f"sonolus/repository/{bgm_hash}"
        if bgm_repo_path not in out:
            out[bgm_repo_path] = bgm_blob

        # --- Copy cover ---
        cover_data = _find_asset(osz_entries, chart.background_filename)
        cover_hash = sha1_hex(cover_data or b"")
        cover_repo_path = f"sonolus/repository/{cover_hash}"
        if cover_repo_path not in out:
            out[cover_repo_path] = cover_data or b""

        # --- Build level item ---
        item = _build_level_item(chart, engine_item, ld_hash, bgm_hash, cover_hash)
        level_items.append(item)

        # --- Write level doc ---
        level_doc = {"item": item}
        level_name = item["name"]
        out[f"sonolus/levels/{level_name}"] = _json_dump(level_doc)

    # --- Write levels list ---
    list_doc = {"pageCount": 1, "items": level_items}
    out["sonolus/levels/list"] = _json_dump(list_doc)
    out["sonolus/levels/info"] = _json_dump({"title": "#TITLE", "subtitle": "#SUBTITLE"})

    # --- Write package doc ---
    package_name = Path(osz_path).stem
    out["sonolus/package"] = _json_dump({"name": f"om2usc-{package_name}", "version": 1})

    # --- Validate repository references ---
    missing = _validate_repo_refs(out)
    if missing:
        print(f"\nWARNING: {len(missing)} missing repository references:", __import__("sys").stderr)
        for m in missing[:10]:
            print(f"  {m}", __import__("sys").stderr)
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more", __import__("sys").stderr)

    # --- Write output ---
    _write_zip(output_path, out)
    print(f"\nWrote: {output_path}")
    print(f"  Levels: {len(level_items)}")
    print(f"  Total entries: {len(out)}")

    return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_osu(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _find_asset(entries: Dict[str, bytes], filename: str) -> Optional[bytes]:
    """Find an asset by filename (case-insensitive) in ZIP entries."""
    if not filename:
        return None
    filename_lower = filename.lower()
    for path, data in entries.items():
        if Path(path).name.lower() == filename_lower:
            return data
    # Try partial match (some .osz have different path structures)
    for path, data in entries.items():
        if filename_lower in Path(path).name.lower():
            return data
    return None


def _copy_engine_resources(
    out: "OrderedDict[str, bytes]",
    engine: Dict[str, bytes],
) -> None:
    """Copy engine resource entries (lists, infos, items, repository)."""
    # Copy all repository blobs
    for path, data in engine.items():
        if path.startswith("sonolus/repository/"):
            out[path] = data

    # Copy category lists, infos, and item docs
    for cat in [*_RESOURCE_CATEGORIES, _ENGINE_CATEGORY]:
        for suffix in ("/list", "/info"):
            path = f"sonolus/{cat}{suffix}"
            data = engine.get(path)
            if data is not None:
                out[path] = data
        # Copy individual items
        for path in _category_item_paths(engine, cat):
            out[path] = engine.get(path, b"")

    # Copy package doc (or create minimal)
    out["sonolus/package"] = engine.get("sonolus/package", _json_dump({"version": 1}))

    # Copy levels info
    for key in ("sonolus/info", "sonolus/levels/info"):
        data = engine.get(key)
        if data is not None:
            out[key] = data


def _validate_repo_refs(entries: Dict[str, bytes]) -> List[str]:
    """Find repository references that don't exist in the package."""
    repo_set = _repository_entries(entries)
    missing: List[str] = []
    seen = set()

    for path, data in entries.items():
        doc = _json_load_safe(entries, path)
        if doc is None:
            continue
        for repo_path in _iter_repo_paths(doc):
            if repo_path not in repo_set and repo_path not in seen:
                seen.add(repo_path)
                missing.append(repo_path)

    return missing
