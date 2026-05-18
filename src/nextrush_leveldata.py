"""USC JSON → NextRUSH+ LevelData converter.

Ports the NextRUSH+ uscToLevelData() logic to Python.  For the osu!mania
MVP we only handle: bpm, timeScaleGroup, single, slide.

Uses the same archetype names and entity graph structure as the upstream
TypeScript converter:
  https://github.com/UntitledCharts/sonolus-next-rush-engine
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Entity builder (mirrors upstream EntityBuilder)
# ---------------------------------------------------------------------------

class EntityBuilder:
    """Builds a single LevelData entity with archetype, values, and refs."""

    __slots__ = ("archetype", "values", "refs")

    def __init__(self, archetype: str) -> None:
        self.archetype = archetype
        self.values: OrderedDict[str, float] = OrderedDict()
        self.refs: OrderedDict[str, EntityBuilder] = OrderedDict()

    def set(self, key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, EntityBuilder):
            self.refs[key] = value
        elif isinstance(value, (int, float)):
            self.values[key] = float(value)
        elif isinstance(value, bool):
            self.values[key] = 1.0 if value else 0.0

    def beat(self) -> float:
        return float(self.values.get("#BEAT", -1))


# ---------------------------------------------------------------------------
# USC → LevelData conversion
# ---------------------------------------------------------------------------

# Sonolus direction mapping (upstream SONOLUS_DIRECTIONS)
_DIRECTIONS = {"left": 1, "up": 0, "right": 2}

# Connector ease mapping (upstream SONOLUS_CONNECTOR_EASES)
_CONNECTOR_EASES = {"outin": 5, "out": 3, "linear": 1, "in": 2, "inout": 4}

_FLOAT_TOLERANCE = 1e-6


def _nearly_equal(a: float, b: float) -> bool:
    return abs(a - b) < _FLOAT_TOLERANCE


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def _apply_ease(ease_type: int, x: float) -> float:
    t = _clamp01(x)
    if ease_type == 2:   # in
        return t * t
    if ease_type == 3:   # out
        return 1 - (1 - t) * (1 - t)
    if ease_type == 4:   # inout
        return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
    if ease_type == 5:   # outin
        return (1 - (1 - 2 * t) * (1 - 2 * t)) / 2 if t < 0.5 else 0.5 + ((2 * t - 1) * (2 * t - 1)) / 2
    return t  # linear


def usc_to_leveldata(usc: Dict[str, Any], offset: float = 0.0) -> Dict[str, Any]:
    """Convert a USC dict to NextRUSH+ LevelData.

    Args:
        usc: USC dictionary with 'offset' and 'objects' keys.
        offset: additional offset in seconds (added to usc.offset).

    Returns:
        LevelData dictionary with 'bgmOffset' and 'entities'.
    """
    usc_offset = float(usc.get("offset", 0.0))
    objects: List[Dict[str, Any]] = usc.get("objects", [])

    all_entities: List[EntityBuilder] = []
    sim_eligible: List[EntityBuilder] = []
    ts_group_refs: List[EntityBuilder] = []

    # --- Collect USC objects by type ---
    bpm_objects = [o for o in objects if o.get("type") == "bpm"]
    ts_groups = [o for o in objects if o.get("type") == "timeScaleGroup"]
    single_notes = [o for o in objects if o.get("type") == "single"]
    slide_notes = [o for o in objects if o.get("type") == "slide"]

    # --- BPM changes ---
    # Sort by beat, build bpm->time index
    bpm_changes = sorted(
        [{"beat": float(o["beat"]), "bpm": float(o["bpm"])} for o in bpm_objects],
        key=lambda c: c["beat"],
    )
    if not bpm_changes:
        bpm_changes = [{"beat": 0.0, "bpm": 120.0}]

    bpm_infos: List[Dict[str, float]] = []
    last_beat = 0.0
    last_time = 0.0
    last_bpm = float(bpm_changes[0]["bpm"])

    for c in bpm_changes:
        beat = float(c["beat"])
        bpm = float(c["bpm"])
        last_time += ((beat - last_beat) * 60.0) / last_bpm
        bpm_infos.append({"beat": beat, "bpm": bpm, "time": last_time})
        last_beat = beat
        last_bpm = bpm

    def beat_to_time(beat: float) -> float:
        if not bpm_infos:
            return (beat * 60.0) / 120.0
        cur = bpm_infos[0]
        for c in bpm_infos:
            if c["beat"] > beat + _FLOAT_TOLERANCE:
                break
            cur = c
        return cur["time"] + ((beat - cur["beat"]) * 60.0) / cur["bpm"]

    def time_to_beat(t: float) -> float:
        if not bpm_infos:
            return (t * 120.0) / 60.0
        cur = bpm_infos[0]
        for c in bpm_infos:
            if c["time"] > t + _FLOAT_TOLERANCE:
                break
            cur = c
        return cur["beat"] + ((t - cur["time"]) * cur["bpm"]) / 60.0

    # Initialization entity
    init = EntityBuilder("Initialization")
    all_entities.append(init)

    # BPM change entities
    for c in bpm_changes:
        bpm_e = EntityBuilder("#BPM_CHANGE")
        bpm_e.set("#BEAT", c["beat"])
        bpm_e.set("#BPM", c["bpm"])
        all_entities.append(bpm_e)

    # --- TimeScale groups ---
    default_tsg = EntityBuilder("#TIMESCALE_GROUP")
    all_entities.append(default_tsg)

    for i, tsg_obj in enumerate(ts_groups):
        group = EntityBuilder("#TIMESCALE_GROUP")
        all_entities.append(group)
        ts_group_refs.append(group)

        changes_raw = tsg_obj.get("changes", [])
        change_entities: List[EntityBuilder] = []
        for ch in changes_raw:
            ce = EntityBuilder("#TIMESCALE_CHANGE")
            ce.set("#BEAT", float(ch.get("beat", 0)))
            ce.set("#TIMESCALE", float(ch.get("timeScale", 1)))
            ce.set("#TIMESCALE_SKIP", 0)
            ce.set("#TIMESCALE_EASE", 0)
            ce.set("hideNotes", 0)
            ce.set("#TIMESCALE_GROUP", group)
            if change_entities:
                change_entities[-1].set("next", ce)
            change_entities.append(ce)
        if change_entities:
            group.set("first", change_entities[0])
            all_entities.extend(change_entities)

    # If no timeScaleGroups, create default with timeScale=1 at beat 0
    if not ts_groups:
        default_change = EntityBuilder("#TIMESCALE_CHANGE")
        default_change.set("#BEAT", 0)
        default_change.set("#TIMESCALE", 1)
        default_change.set("#TIMESCALE_SKIP", 0)
        default_change.set("#TIMESCALE_EASE", 0)
        default_change.set("hideNotes", 0)
        default_change.set("#TIMESCALE_GROUP", default_tsg)
        default_tsg.set("first", default_change)
        all_entities.append(default_change)

    def _get_tsg(index: int = 0) -> EntityBuilder:
        if 0 <= index < len(ts_group_refs):
            return ts_group_refs[index]
        return default_tsg

    # --- Single notes ---
    for note in single_notes:
        beat = float(note.get("beat", 0))
        lane = float(note.get("lane", 0))
        size = float(note.get("size", 1))
        critical = bool(note.get("critical", False))
        trace = bool(note.get("trace", False))
        direction = note.get("direction")  # 'left', 'up', 'right', or None

        tsg_idx = int(note.get("timeScaleGroup", 0))
        tsg_ref = _get_tsg(tsg_idx)

        # Determine archetype name (mirrors upstream naming)
        name_parts = ["Critical"] if critical else ["Normal"]
        if direction is not None:
            name_parts.append("TraceFlick" if trace else "Flick")
        else:
            name_parts.append("Trace" if trace else "Tap")
        name_parts.append("Note")
        archetype = "".join(name_parts)

        n = EntityBuilder(archetype)
        n.set("#BEAT", beat)
        n.set("lane", lane)
        n.set("size", size)
        n.set("direction", _DIRECTIONS.get(direction, 0) if direction else 0)
        n.set("isAttached", 0)
        n.set("connectorEase", _CONNECTOR_EASES["linear"])
        n.set("isSeparator", 0)
        n.set("segmentKind", 2 if critical else 1)
        n.set("segmentAlpha", 1)
        n.set("segmentLayer", 0)
        n.set("#TIMESCALE_GROUP", tsg_ref)
        all_entities.append(n)
        sim_eligible.append(n)

    # --- Slide notes (holds) ---
    for slide in slide_notes:
        critical = bool(slide.get("critical", False))
        connections = slide.get("connections", [])
        if len(connections) < 2:
            continue  # malformed slide, skip

        # Build connection intermediates
        conn_entities: List[EntityBuilder] = []
        for ci, conn in enumerate(connections):
            conn_type = conn.get("type", "")
            beat = float(conn.get("beat", 0))
            lane = float(conn.get("lane", 0))
            size = float(conn.get("size", 1))
            tsg_idx = int(conn.get("timeScaleGroup", 0))
            tsg_ref = _get_tsg(tsg_idx)

            ease_str = conn.get("ease", "linear")
            ease_val = _CONNECTOR_EASES.get(ease_str, 1)
            judge_type = conn.get("judgeType", "normal")

            if conn_type == "start":
                if judge_type == "none":
                    archetype = "AnchorNote"
                else:
                    prefix = "Critical" if critical else "Normal"
                    mid = "HeadTrace" if judge_type == "trace" else "HeadTap"
                    archetype = f"{prefix}{mid}Note"
            elif conn_type == "end":
                if judge_type == "none":
                    archetype = "AnchorNote"
                else:
                    prefix = "Critical" if critical else "Normal"
                    direction = conn.get("direction")
                    if direction:
                        archetype = f"{prefix}TailFlickNote"
                    elif judge_type == "trace":
                        archetype = f"{prefix}TailTraceNote"
                    else:
                        archetype = f"{prefix}TailReleaseNote"
            elif conn_type == "tick":
                archetype = "NormalTickNote"
            elif conn_type == "attach":
                archetype = "AnchorNote"
            else:
                continue  # skip unknown connection type

            c = EntityBuilder(archetype)
            c.set("#BEAT", beat)
            c.set("lane", lane)
            c.set("size", size)
            c.set("direction", _DIRECTIONS.get(conn.get("direction"), 0)
                   if conn.get("direction") and conn_type == "end" else 0)
            c.set("isAttached", 1 if conn_type == "attach" else 0)
            c.set("connectorEase", ease_val)
            c.set("isSeparator", 0)
            c.set("segmentKind", 2 if critical else 1)
            c.set("segmentAlpha", 1)
            c.set("segmentLayer", 0)
            c.set("#TIMESCALE_GROUP", tsg_ref)

            conn_entities.append(c)
            all_entities.append(c)
            if conn_type in ("start", "end") and judge_type != "none":
                sim_eligible.append(c)

        # Link start→end chain via 'next' refs
        for j in range(len(conn_entities) - 1):
            if conn_entities[j].archetype != "AnchorNote":
                conn_entities[j].set("next", conn_entities[j + 1])
            if conn_entities[j + 1].archetype != "AnchorNote":
                # Set prev on the next entity
                pass  # upstream doesn't set prev explicitly

    # --- SimLine generation ---
    # Group sim-eligible notes by beat (within tolerance)
    sim_eligible.sort(key=lambda e: e.beat())
    sim_groups: List[List[EntityBuilder]] = []
    current_group: List[EntityBuilder] = []
    for note in sim_eligible:
        if not current_group or _nearly_equal(
            note.beat(), current_group[0].beat()
        ):
            current_group.append(note)
        else:
            if len(current_group) > 1:
                sim_groups.append(current_group)
            current_group = [note]
    if len(current_group) > 1:
        sim_groups.append(current_group)

    for group in sim_groups:
        # Sort by lane for proper left-right pairing
        group.sort(key=lambda e: float(e.values.get("lane", 0)))
        for j in range(len(group) - 1):
            sim = EntityBuilder("SimLine")
            sim.set("left", group[j])
            sim.set("right", group[j + 1])
            all_entities.append(sim)

    # --- Serialize entities ---
    entity_names: Dict[EntityBuilder, str] = {}
    counter = [0]

    def get_name(entity: EntityBuilder) -> str:
        if entity not in entity_names:
            entity_names[entity] = format(counter[0], "x")
            counter[0] += 1
        return entity_names[entity]

    serialized: List[Dict[str, Any]] = []
    for entity in all_entities:
        data: List[Dict[str, Any]] = []
        for key, val in entity.values.items():
            data.append({"name": key, "value": val})
        for key, ref in entity.refs.items():
            data.append({"name": key, "ref": get_name(ref)})
        serialized.append({
            "archetype": entity.archetype,
            "name": get_name(entity),
            "data": data,
        })

    return {
        "bgmOffset": usc_offset + offset,
        "entities": serialized,
    }


# ---------------------------------------------------------------------------
# LevelData serialization (gzip + SHA1)
# ---------------------------------------------------------------------------

def serialize_leveldata(leveldata: Dict[str, Any]) -> bytes:
    """Serialize LevelData to gzipped JSON bytes (stable output)."""
    json_bytes = json.dumps(leveldata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(json_bytes, mtime=0)


def sha1_hex(data: bytes) -> str:
    """SHA1 hex digest."""
    return hashlib.sha1(data).hexdigest()


def leveldata_blob(leveldata: Dict[str, Any]) -> Tuple[bytes, str]:
    """Return (gzipped bytes, SHA1 hex) for a LevelData dict."""
    raw = serialize_leveldata(leveldata)
    return raw, sha1_hex(raw)
