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
import json
import re
import zipfile
from io import BytesIO
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from .osu_parser import OsuChart
from .osu_to_usc import osu_to_usc
from .nextrush_leveldata import (
    leveldata_blob,
    sha1_hex,
    usc_to_leveldata,
)

ProgressCallback = Callable[[int, int, str], None]

BACKGROUND_MODES = {"default", "original"}
DEFAULT_HIDDEN_TICK_INTERVAL = 0.5
SPARSE_HIDDEN_TICK_INTERVAL = 1.0


@dataclass
class ChartSource:
    """A parsed chart plus access to its source .osz assets."""

    osz_path: str
    osu_path: str
    entries: "OrderedDict[str, bytes]"
    chart: OsuChart


@dataclass(frozen=True)
class ImageResources:
    """PNG resources derived from a source image for Sonolus import."""

    cover: bytes
    background: bytes
    aspect_ratio: float


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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _emit_progress(
    callback: Optional[ProgressCallback],
    current: int,
    total: int,
    message: str,
) -> None:
    if callback is not None:
        callback(current, total, message)


def _safe_slug(value: str, fallback: str = "item", max_length: int = 96) -> str:
    """Return an ASCII Sonolus-safe item name fragment."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = fallback
    return slug[:max_length].strip("-") or fallback


def _unique_name(base: str, used: Set[str], max_length: int = 120) -> str:
    """Make a stable unique name for a Sonolus item path."""
    base = _safe_slug(base, max_length=max_length)
    candidate = base
    index = 2
    while candidate in used:
        suffix = f"-{index}"
        candidate = f"{base[:max_length - len(suffix)]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# Sonolus metadata helpers
# ---------------------------------------------------------------------------

_RESOURCE_CATEGORIES = ["skins", "backgrounds", "effects", "particles"]
_ENGINE_CATEGORY = "engines"


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


def _put_repository_blob(out: "OrderedDict[str, bytes]", data: bytes) -> str:
    """Write a repository blob and return its SHA-1 hash."""
    resource_hash = sha1_hex(data)
    out.setdefault(f"sonolus/repository/{resource_hash}", data)
    return resource_hash


def _put_json_resource(out: "OrderedDict[str, bytes]", obj: Any) -> str:
    """Write a gzipped JSON resource and return its SHA-1 hash."""
    blob = gzip.compress(_json_dump(obj), mtime=0)
    return _put_repository_blob(out, blob)


def _resource_ref(resource_hash: Optional[str]) -> Dict[str, str]:
    """Build a Sonolus repository resource reference."""
    if not resource_hash:
        return {}
    return {
        "hash": resource_hash,
        "url": f"/sonolus/repository/{resource_hash}",
    }


def _srl_hash(ref: Any) -> Optional[str]:
    """Return the hash from a Sonolus resource reference."""
    if isinstance(ref, dict):
        value = ref.get("hash")
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_image_resources(image_data: bytes) -> Optional[ImageResources]:
    """Convert an osu background image into Sonolus-friendly PNG resources."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        print("    WARNING: Pillow is required to convert images to Sonolus PNG resources.")
        return None

    try:
        with Image.open(BytesIO(image_data)) as image:
            image = ImageOps.exif_transpose(image)
            if getattr(image, "is_animated", False):
                image.seek(0)

            width, height = image.size
            if width <= 0 or height <= 0:
                return None

            mode = "RGBA" if "A" in image.getbands() else "RGB"
            base = image.convert(mode)
            background = base.copy()
            background.thumbnail((1920, 1920), Image.Resampling.LANCZOS)

            bg_buffer = BytesIO()
            background.save(bg_buffer, format="PNG", optimize=True)

            cover = background.copy()
            cover_width, cover_height = cover.size
            side = min(cover_width, cover_height)
            left = (cover_width - side) // 2
            top = (cover_height - side) // 2
            cover = cover.crop((left, top, left + side, top + side))
            cover.thumbnail((512, 512), Image.Resampling.LANCZOS)

            cover_buffer = BytesIO()
            cover.save(cover_buffer, format="PNG", optimize=True)

            return ImageResources(
                cover=cover_buffer.getvalue(),
                background=bg_buffer.getvalue(),
                aspect_ratio=width / height,
            )
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        print(f"    WARNING: Failed to convert background image to PNG: {exc}")
        return None


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
    level_name: str,
    leveldata_hash: str,
    bgm_hash: Optional[str],
    cover_hash: Optional[str],
    background_item: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a Sonolus level item from a parsed chart."""
    base_name = chart.title
    if chart.artist:
        base_name = f"{chart.artist} - {base_name}"

    title = base_name
    if chart.version:
        title = f"{base_name} [{chart.version}]"

    item = {
        "name": level_name,
        "version": 1,
        "title": title,
        "artists": chart.artist,
        "author": chart.creator,
        "rating": 0,
        "tags": [],
        "engine": copy.deepcopy(engine_item),
        "useSkin": {"useDefault": True},
        "useBackground": {"useDefault": True},
        "useEffect": {"useDefault": True},
        "useParticle": {"useDefault": True},
        "cover": _resource_ref(cover_hash),
        "bgm": _resource_ref(bgm_hash),
        "preview": _resource_ref(bgm_hash),
        "data": _resource_ref(leveldata_hash),
    }
    if background_item is not None:
        item["useBackground"] = {
            "useDefault": False,
            "item": copy.deepcopy(background_item),
        }
    return item


def _build_background_item(
    chart: OsuChart,
    background_name: str,
    thumbnail_hash: str,
    image_hash: str,
    data_hash: str,
    configuration_hash: str,
    template: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a Sonolus background item using the engine background template."""
    item = copy.deepcopy(template) if template else {}
    item.update({
        "name": background_name,
        "version": 2,
        "title": chart.title or "osu!mania Background",
        "subtitle": chart.version or "Converted osu!mania background",
        "author": chart.creator or "om2usc",
        "tags": [],
    })
    item["thumbnail"] = _resource_ref(thumbnail_hash)
    item["data"] = _resource_ref(data_hash)
    item["image"] = _resource_ref(image_hash)
    item["configuration"] = _resource_ref(configuration_hash)
    return item


def _append_background_indexes(out: "OrderedDict[str, bytes]", item: Dict[str, Any]) -> None:
    """Append a generated background to copied background list/info docs."""
    list_doc = _json_load_safe(out, "sonolus/backgrounds/list")
    if not isinstance(list_doc, dict):
        list_doc = {"pageCount": 1, "items": []}
    items = list_doc.setdefault("items", [])
    if isinstance(items, list) and not any(i.get("name") == item["name"] for i in items if isinstance(i, dict)):
        items.append(copy.deepcopy(item))
    list_doc["pageCount"] = max(1, int(list_doc.get("pageCount") or 1))
    out["sonolus/backgrounds/list"] = _json_dump(list_doc)

    info_doc = _json_load_safe(out, "sonolus/backgrounds/info")
    if not isinstance(info_doc, dict):
        info_doc = {"sections": [{"title": "#BACKGROUND", "itemType": "background", "items": []}]}
    sections = info_doc.setdefault("sections", [])
    if not sections:
        sections.append({"title": "#BACKGROUND", "itemType": "background", "items": []})
    section = sections[0]
    section_items = section.setdefault("items", [])
    if isinstance(section_items, list) and not any(i.get("name") == item["name"] for i in section_items if isinstance(i, dict)):
        section_items.append(copy.deepcopy(item))
    out["sonolus/backgrounds/info"] = _json_dump(info_doc)


def _levels_info(level_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build levels/info using the section shape expected by Sonolus packages."""
    return {
        "sections": [
            {
                "title": "#NEWEST",
                "itemType": "level",
                "items": copy.deepcopy(level_items),
            },
        ],
    }


def _level_details(item: Dict[str, Any], chart: OsuChart, source_path: str) -> Dict[str, Any]:
    """Build the level details endpoint document required by Sonolus."""
    details = [
        f"Converted from osu!mania ({chart.key_count}K).",
        f"Source package: {Path(source_path).name}.",
    ]
    if chart.version:
        details.append(f"Difficulty: {chart.version}.")

    return {
        "item": item,
        "description": "\n".join(details),
        "actions": [],
        "hasCommunity": False,
        "leaderboards": [],
        "sections": [],
    }


def _service_info(title: str) -> Dict[str, Any]:
    """Build root service info instead of leaking metadata from the engine pack."""
    return {
        "title": title,
        "buttons": [
            {"type": "level", "badgeCount": 0},
            {"type": "skin", "badgeCount": 0},
            {"type": "background", "badgeCount": 0},
            {"type": "effect", "badgeCount": 0},
            {"type": "particle", "badgeCount": 0},
            {"type": "engine", "badgeCount": 0},
        ],
        "configuration": {"options": []},
    }


def _package_doc() -> Dict[str, bool]:
    """Build the minimal package doc used by importable Sonolus SCP examples."""
    return {"shouldUpdate": False}


# ---------------------------------------------------------------------------
# Main SCP builder
# ---------------------------------------------------------------------------

def build_scp(
    osz_path: str,
    engine_path: str,
    output_path: str,
    single_version: Optional[str] = None,
    tail_mode: str = "release",
    background_mode: str = "default",
    progress_callback: Optional[ProgressCallback] = None,
    tinged_columns: bool = False,
    sparse_hidden_ticks: bool = False,
) -> int:
    """Build a complete .scp package from .osz + engine.scp.

    Returns 0 on success, 1 on error.
    """
    return build_merged_scp(
        [osz_path],
        engine_path,
        output_path,
        single_version=single_version,
        tail_mode=tail_mode,
        background_mode=background_mode,
        package_name=Path(osz_path).stem,
        progress_callback=progress_callback,
        tinged_columns=tinged_columns,
        sparse_hidden_ticks=sparse_hidden_ticks,
    )


def build_merged_scp(
    osz_paths: Iterable[str],
    engine_path: str,
    output_path: str,
    single_version: Optional[str] = None,
    tail_mode: str = "release",
    background_mode: str = "default",
    package_name: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
    tinged_columns: bool = False,
    sparse_hidden_ticks: bool = False,
) -> int:
    """Build one .scp package containing charts from one or more .osz files."""
    import sys

    paths = [str(p) for p in osz_paths]
    if not paths:
        print("No .osz files selected.", file=sys.stderr)
        return 1
    if background_mode not in BACKGROUND_MODES:
        print(f"Unsupported background mode: {background_mode}", file=sys.stderr)
        return 1

    try:
        chart_sources = _collect_chart_sources(paths, single_version)
        engine_entries = _read_zip_entries(engine_path)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"Failed to read input: {exc}", file=sys.stderr)
        return 1

    if not chart_sources:
        print("No valid mania charts found.", file=sys.stderr)
        return 1

    engine_item, background_template = _load_engine_items(engine_entries, engine_path)
    if engine_item is None:
        return 1

    print(f"Found {len(chart_sources)} valid chart(s)")
    _emit_progress(progress_callback, 0, len(chart_sources), "Preparing package")

    out: "OrderedDict[str, bytes]" = OrderedDict()
    _copy_engine_resources(out, engine_entries)

    level_items: List[Dict[str, Any]] = []
    used_level_names: Set[str] = set()
    used_background_names: Set[str] = set()

    for index, source in enumerate(chart_sources, start=1):
        chart = source.chart
        source_slug = _safe_slug(Path(source.osz_path).stem, fallback="osz", max_length=48)
        level_name = _unique_name(
            f"om2usc-{source_slug}-{chart.version}",
            used_level_names,
        )
        print(f"  Processing: {chart.version} ({chart.key_count}K, {len(chart.hit_objects)} notes)")
        _emit_progress(
            progress_callback,
            index - 1,
            len(chart_sources),
            f"Converting {Path(source.osz_path).name}: {chart.version}",
        )

        usc = osu_to_usc(
            chart,
            tail_mode=tail_mode,
            tinged_columns=tinged_columns,
        )
        leveldata = usc_to_leveldata(
            usc,
            hidden_tick_interval=(
                SPARSE_HIDDEN_TICK_INTERVAL
                if sparse_hidden_ticks
                else DEFAULT_HIDDEN_TICK_INTERVAL
            ),
        )
        ld_blob, ld_hash = leveldata_blob(leveldata)
        _put_repository_blob(out, ld_blob)

        bgm_hash: Optional[str] = None
        bgm_data = _find_asset(source.entries, chart.audio_filename)
        if bgm_data is None:
            print(f"    WARNING: BGM '{chart.audio_filename}' not found in .osz", file=sys.stderr)
        else:
            # Sonolus audio repository blobs are raw media files; only LevelData is gzipped.
            bgm_hash = _put_repository_blob(out, bgm_data)

        cover_hash: Optional[str] = None
        background_image_hash: Optional[str] = None
        background_data_hash: Optional[str] = None
        background_configuration_hash: Optional[str] = (
            _srl_hash(background_template.get("configuration"))
            if isinstance(background_template, dict)
            else None
        )
        cover_data = _find_asset(source.entries, chart.background_filename)
        if cover_data is not None:
            image_resources = _normalize_image_resources(cover_data)
            if image_resources is None:
                print("    WARNING: Using original image bytes; Sonolus expects PNG image resources.")
                cover_hash = _put_repository_blob(out, cover_data)
                if background_mode == "original":
                    background_image_hash = cover_hash
            else:
                cover_hash = _put_repository_blob(out, image_resources.cover)
                if background_mode == "original":
                    background_image_hash = _put_repository_blob(out, image_resources.background)
                    background_data_hash = _put_json_resource(out, {
                        "aspectRatio": round(image_resources.aspect_ratio, 6),
                        "fit": "cover",
                        "color": "#000000",
                    })
                    if background_configuration_hash is None:
                        background_configuration_hash = _put_json_resource(out, {
                            "blur": 0,
                            "mask": "#0000",
                        })

        background_item = None
        if (
            background_mode == "original"
            and cover_hash
            and background_image_hash
            and background_data_hash
            and background_configuration_hash
        ):
            background_name = _unique_name(
                f"om2usc-bg-{source_slug}-{chart.version}",
                used_background_names,
            )
            background_item = _build_background_item(
                chart,
                background_name,
                cover_hash,
                background_image_hash,
                background_data_hash,
                background_configuration_hash,
                background_template,
            )
            out[f"sonolus/backgrounds/{background_name}"] = _json_dump({
                "item": background_item,
                "actions": [],
                "hasCommunity": False,
                "leaderboards": [],
                "sections": [],
            })
            _append_background_indexes(out, background_item)

        item = _build_level_item(
            chart,
            engine_item,
            level_name,
            ld_hash,
            bgm_hash,
            cover_hash,
            background_item=background_item,
        )
        level_items.append(item)
        out[f"sonolus/levels/{level_name}"] = _json_dump(_level_details(item, chart, source.osz_path))
        _emit_progress(
            progress_callback,
            index,
            len(chart_sources),
            f"Finished {chart.version}",
        )

    resolved_package_name = package_name or _package_name_from_paths(paths)
    package_title = f"om2usc-{_safe_slug(resolved_package_name, fallback='package')}"
    out["sonolus/levels/list"] = _json_dump({"pageCount": 1, "items": level_items})
    out["sonolus/levels/info"] = _json_dump(_levels_info(level_items))
    out["sonolus/info"] = _json_dump(_service_info(package_title))
    out["sonolus/package"] = _json_dump(_package_doc())

    missing = _validate_repo_refs(out)
    if missing:
        print(f"\nWARNING: {len(missing)} missing repository references:", file=sys.stderr)
        for missing_path in missing[:10]:
            print(f"  {missing_path}", file=sys.stderr)
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more", file=sys.stderr)

    _write_zip(output_path, out)
    print(f"\nWrote: {output_path}")
    print(f"  Levels: {len(level_items)}")
    print(f"  Total entries: {len(out)}")
    _emit_progress(progress_callback, len(chart_sources), len(chart_sources), f"Wrote {output_path}")
    return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_chart_sources(
    osz_paths: Iterable[str],
    single_version: Optional[str],
) -> List[ChartSource]:
    from .osu_parser import parse_osu as _parse_osu

    chart_sources: List[ChartSource] = []
    for osz_path in osz_paths:
        entries = _read_zip_entries(osz_path)
        for path, data in entries.items():
            if not path.endswith(".osu"):
                continue
            text = _decode_osu(data)
            chart = _parse_osu(text)
            if not (chart.is_mania and not chart.is_placeholder and chart.key_count > 0):
                continue
            if single_version and chart.version != single_version:
                continue
            chart_sources.append(ChartSource(
                osz_path=osz_path,
                osu_path=path,
                entries=entries,
                chart=chart,
            ))
    return chart_sources


def _load_engine_items(
    engine_entries: Dict[str, bytes],
    engine_path: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    import sys

    engine_doc = _json_load_safe(engine_entries, "sonolus/engines/NextRUSH_P")
    if not engine_doc:
        print(f"Engine not found in {engine_path}", file=sys.stderr)
        return None, None
    engine_item = engine_doc.get("item", engine_doc) if isinstance(engine_doc, dict) else engine_doc

    background_doc = _json_load_safe(engine_entries, "sonolus/backgrounds/PLEASE-SELECT")
    background_template = None
    if isinstance(background_doc, dict):
        template = background_doc.get("item")
        if isinstance(template, dict):
            background_template = template
    if background_template is None and isinstance(engine_item, dict):
        template = engine_item.get("background")
        if isinstance(template, dict):
            background_template = template

    return engine_item, background_template


def _package_name_from_paths(paths: List[str]) -> str:
    if len(paths) == 1:
        return Path(paths[0]).stem
    digest = sha1_hex("|".join(Path(p).stem for p in paths).encode("utf-8"))[:8]
    return f"merged-{len(paths)}-osz-{digest}"


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
