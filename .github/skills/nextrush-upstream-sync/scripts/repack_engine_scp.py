#!/usr/bin/env python3
"""Repack om2pjsk-usc's engine.scp with freshly built NextRUSH+ runtime blobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any


ENGINE_BLOBS = {
    "configuration": "EngineConfiguration",
    "playData": "EnginePlayData",
    "watchData": "EngineWatchData",
    "previewData": "EnginePreviewData",
    "tutorialData": "EngineTutorialData",
    "rom": "EngineRom",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-scp", default="engine.scp", type=Path)
    parser.add_argument("--dist-engine", required=True, type=Path)
    parser.add_argument("--upstream-version", required=True)
    parser.add_argument("--engine-name", default="NextRUSH_P")
    parser.add_argument(
        "--upstream-url",
        default="https://github.com/UntitledCharts/sonolus-next-rush-engine",
    )
    return parser.parse_args()


def read_zip_entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def json_load(entries: dict[str, bytes], name: str) -> Any:
    return json.loads(entries[name].decode("utf-8"))


def json_dump(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def collect_hashes(value: Any) -> set[str]:
    hashes: set[str] = set()
    if isinstance(value, dict):
        maybe_hash = value.get("hash")
        if isinstance(maybe_hash, str):
            hashes.add(maybe_hash)
        for child in value.values():
            hashes.update(collect_hashes(child))
    elif isinstance(value, list):
        for child in value:
            hashes.update(collect_hashes(child))
    return hashes


def update_item_in_list(items: list[Any], engine_name: str, engine_item: dict[str, Any]) -> list[Any]:
    return [
        engine_item if isinstance(item, dict) and item.get("name") == engine_name else item
        for item in items
    ]


def replace_file(src: Path, dst: Path) -> None:
    try:
        src.replace(dst)
    except PermissionError:
        shutil.copyfile(src, dst)
        try:
            src.unlink()
        except PermissionError:
            pass


def main() -> int:
    args = parse_args()
    engine_scp = args.engine_scp
    dist_engine = args.dist_engine
    engine_doc_path = f"sonolus/engines/{args.engine_name}"

    missing = [name for name in ENGINE_BLOBS.values() if not (dist_engine / name).is_file()]
    if missing:
        raise SystemExit(f"Missing engine build output: {', '.join(missing)}")

    entries = read_zip_entries(engine_scp)
    if engine_doc_path not in entries:
        raise SystemExit(f"{engine_scp} does not contain {engine_doc_path}")

    engine_doc = json_load(entries, engine_doc_path)
    engine_item = engine_doc["item"]
    old_runtime_hashes = {
        engine_item[field]["hash"]
        for field in ENGINE_BLOBS
        if isinstance(engine_item.get(field), dict) and "hash" in engine_item[field]
    }

    new_blobs: dict[str, bytes] = {}
    for field, filename in ENGINE_BLOBS.items():
        data = (dist_engine / filename).read_bytes()
        digest = hash_bytes(data)
        new_blobs[digest] = data
        engine_item[field] = {
            "hash": digest,
            "url": f"/sonolus/repository/{digest}",
        }

    engine_item["description"] = (
        f"\nNext RUSH+ Sonolus engine.\n\n{args.upstream_url}\n{args.upstream_version}"
    )

    engine_doc["item"] = engine_item
    entries[engine_doc_path] = json_dump(engine_doc)

    engines_list = json_load(entries, "sonolus/engines/list")
    engines_list["items"] = update_item_in_list(
        engines_list.get("items", []),
        args.engine_name,
        engine_item,
    )
    entries["sonolus/engines/list"] = json_dump(engines_list)

    engines_info = json_load(entries, "sonolus/engines/info")
    for section in engines_info.get("sections", []):
        if section.get("itemType") == "engine":
            section["items"] = update_item_in_list(
                section.get("items", []),
                args.engine_name,
                engine_item,
            )
    entries["sonolus/engines/info"] = json_dump(engines_info)

    if "sonolus/package" in entries:
        package_doc = json_load(entries, "sonolus/package")
        package_doc["title"] = "om2pjsk-usc Engine Pack"
        entries["sonolus/package"] = json_dump(package_doc)

    if "sonolus/info" in entries:
        info_doc = json_load(entries, "sonolus/info")
        info_doc["title"] = "om2pjsk-usc Engine Pack"
        info_doc["description"] = (
            f"Bundled NextRUSH+ {args.upstream_version} target engine resources for om2pjsk-usc."
        )
        entries["sonolus/info"] = json_dump(info_doc)

    referenced_hashes: set[str] = set()
    for name, data in entries.items():
        if not name.startswith("sonolus/repository/"):
            try:
                referenced_hashes.update(collect_hashes(json.loads(data.decode("utf-8"))))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
    referenced_hashes.update(new_blobs)

    old_runtime_paths = {
        f"sonolus/repository/{digest}"
        for digest in old_runtime_hashes
        if digest not in referenced_hashes
    }
    new_runtime_paths = {f"sonolus/repository/{digest}" for digest in new_blobs}

    temp_path = engine_scp.with_suffix(engine_scp.suffix + ".new")
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(entries):
            if name in old_runtime_paths or name in new_runtime_paths:
                continue
            zf.writestr(name, entries[name])
        for digest, data in sorted(new_blobs.items()):
            zf.writestr(f"sonolus/repository/{digest}", data)

    with zipfile.ZipFile(temp_path, "r") as zf:
        names = set(zf.namelist())
        item = json.loads(zf.read(engine_doc_path).decode("utf-8"))["item"]
        for field in ENGINE_BLOBS:
            digest = item[field]["hash"]
            repo_path = f"sonolus/repository/{digest}"
            if repo_path not in names:
                raise SystemExit(f"Missing repository blob for {field}: {digest}")
            if hash_bytes(zf.read(repo_path)) != digest:
                raise SystemExit(f"Hash mismatch for {field}: {digest}")

    replace_file(temp_path, engine_scp)
    print(f"Updated {engine_scp} from {dist_engine}")
    for field in ENGINE_BLOBS:
        print(f"{field}: {engine_item[field]['hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
