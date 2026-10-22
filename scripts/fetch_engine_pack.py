"""Download an engine and its default resources as a self-contained SCP pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "om2pjsk-usc engine pack updater"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def fetch_engine_pack(server: str, engine_name: str, output: Path) -> None:
    server = server.rstrip("/")
    details = json.loads(fetch(f"{server}/sonolus/engines/{quote(engine_name, safe='')}"))
    engine = details["item"]
    if engine.get("name") != engine_name:
        raise ValueError("The server returned a different engine")

    entries: dict[str, bytes] = {}

    def localize(value):
        if isinstance(value, dict):
            if "url" in value and "hash" in value:
                digest = value["hash"]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{40}", digest):
                    raise ValueError(f"Invalid resource hash: {digest!r}")
                path = f"sonolus/repository/{digest}"
                if path not in entries:
                    data = fetch(urljoin(server + "/", value["url"]))
                    if hashlib.sha1(data).hexdigest() != digest:
                        raise ValueError(f"Hash mismatch: {value['url']}")
                    entries[path] = data
                    print(f"Downloaded {digest} ({len(data)} bytes)", flush=True)
                value["url"] = f"/{path}"
            for child in value.values():
                localize(child)
        elif isinstance(value, list):
            for child in value:
                localize(child)

    localize(engine)

    def put_json(path, value):
        entries[path] = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    categories = {"engines": [engine]}
    for kind in ("skin", "background", "effect", "particle"):
        categories[f"{kind}s"] = [engine[kind]]
    for category, items in categories.items():
        for item in items:
            name = item["name"]
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                raise ValueError(f"Unsafe resource name: {name!r}")
            put_json(f"sonolus/{category}/{name}", {
                "item": item,
                "description": details.get("description", "") if category == "engines" else "",
                "actions": [],
                "hasCommunity": False,
                "leaderboards": [],
                "sections": [],
            })
        put_json(f"sonolus/{category}/list", {"pageCount": 1, "items": items})
        put_json(f"sonolus/{category}/info", {"sections": [{
            "title": f"#{category[:-1].upper()}", "itemType": category[:-1], "items": items,
        }]})

    put_json("sonolus/package", {"shouldUpdate": False})
    put_json("sonolus/info", {
        "title": f"{engine['title']} Engine Pack",
        "description": f"Official resource snapshot from {server}\nPlayData SHA1: {engine['playData']['hash']}",
        "buttons": [{"type": category[:-1]} for category in categories],
        "configuration": {"options": []},
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".new")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in entries.items():
            archive.writestr(path, data)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError("Resource pack failed ZIP integrity verification")
    temporary.replace(output)
    print(f"Wrote {output}: {len(entries)} entries")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--engine-name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    fetch_engine_pack(args.server, args.engine_name, args.out)


if __name__ == "__main__":
    main()
