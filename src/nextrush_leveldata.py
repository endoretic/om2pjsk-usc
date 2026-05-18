"""USC JSON -> NextRUSH+ LevelData converter.

Ports the NextRUSH+ uscToLevelData() logic to Python for the subset this
project emits: bpm, timeScaleGroup, single, and slide.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Entity builder
# ---------------------------------------------------------------------------

class EntityBuilder:
    """Builds a single LevelData entity with values and entity references."""

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
        elif isinstance(value, bool):
            self.values[key] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            self.values[key] = float(value)

    def beat(self) -> float:
        return float(self.values.get("#BEAT", -1))


# ---------------------------------------------------------------------------
# USC -> LevelData conversion
# ---------------------------------------------------------------------------

_DIRECTIONS = {"left": 1, "up": 0, "right": 2}
_CONNECTOR_EASES = {"outin": 5, "out": 3, "linear": 1, "in": 2, "inout": 4}
_FLOAT_TOLERANCE = 1e-6
_SIMLINE_TOLERANCE = 1e-2


def _nearly_equal(a: float, b: float, tolerance: float = _FLOAT_TOLERANCE) -> bool:
    return abs(a - b) < tolerance


def usc_to_leveldata(usc: Dict[str, Any], offset: float = 0.0) -> Dict[str, Any]:
    """Convert a USC dict to NextRUSH+ LevelData."""
    usc_offset = float(usc.get("offset", 0.0))
    objects: List[Dict[str, Any]] = usc.get("objects", [])

    all_entities: List[EntityBuilder] = []
    sim_eligible: List[EntityBuilder] = []
    ts_group_refs: List[EntityBuilder] = []

    bpm_objects = [o for o in objects if o.get("type") == "bpm"]
    ts_groups = [o for o in objects if o.get("type") == "timeScaleGroup"]
    single_notes = [o for o in objects if o.get("type") == "single"]
    slide_notes = [o for o in objects if o.get("type") == "slide"]

    bpm_changes = sorted(
        [{"beat": float(o["beat"]), "bpm": float(o["bpm"])} for o in bpm_objects],
        key=lambda c: c["beat"],
    )
    if not bpm_changes:
        bpm_changes = [{"beat": 0.0, "bpm": 160.0}]

    all_entities.append(EntityBuilder("Initialization"))

    for c in bpm_changes:
        bpm_e = EntityBuilder("#BPM_CHANGE")
        bpm_e.set("#BEAT", c["beat"])
        bpm_e.set("#BPM", c["bpm"])
        all_entities.append(bpm_e)

    if not ts_groups:
        ts_groups = [{"type": "timeScaleGroup", "changes": [{"beat": 0, "timeScale": 1}]}]

    for tsg_obj in ts_groups:
        group = EntityBuilder("#TIMESCALE_GROUP")
        all_entities.append(group)
        ts_group_refs.append(group)

        previous_change: Optional[EntityBuilder] = None
        changes = sorted(tsg_obj.get("changes", []), key=lambda c: float(c.get("beat", 0)))
        for change in changes:
            change_e = EntityBuilder("#TIMESCALE_CHANGE")
            change_e.set("#BEAT", float(change.get("beat", 0)))
            time_scale = float(change.get("timeScale", 1))
            change_e.set("#TIMESCALE", 0.000001 if time_scale == 0 else time_scale)
            change_e.set("#TIMESCALE_SKIP", 0)
            change_e.set("#TIMESCALE_EASE", 0)
            change_e.set("hideNotes", 0)
            change_e.set("#TIMESCALE_GROUP", group)

            if previous_change is None:
                group.set("first", change_e)
            else:
                previous_change.set("next", change_e)
            previous_change = change_e
            all_entities.append(change_e)

    def get_tsg(index: int = 0) -> EntityBuilder:
        if 0 <= index < len(ts_group_refs):
            return ts_group_refs[index]
        return ts_group_refs[0]

    # --- Single notes ---
    for note in single_notes:
        beat = float(note.get("beat", 0))
        lane = float(note.get("lane", 0))
        size = float(note.get("size", 1))
        critical = bool(note.get("critical", False))
        trace = bool(note.get("trace", False))
        direction = note.get("direction")

        name_parts = ["Critical" if critical else "Normal"]
        if direction is None:
            name_parts.append("Trace" if trace else "Tap")
        else:
            name_parts.append("TraceFlick" if trace else "Flick")
        name_parts.append("Note")

        n = EntityBuilder("".join(name_parts))
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
        n.set("#TIMESCALE_GROUP", get_tsg(int(note.get("timeScaleGroup", 0))))
        all_entities.append(n)
        sim_eligible.append(n)

    # --- Slide notes (holds) ---
    for slide in slide_notes:
        slide_type = slide.get("type", "slide")
        slide_critical = bool(slide.get("critical", False))
        connections = sorted(slide.get("connections", []), key=lambda c: float(c.get("beat", 0)))
        if not connections:
            continue

        prev_joint: Optional[EntityBuilder] = None
        prev_note: Optional[EntityBuilder] = None
        head_note: Optional[EntityBuilder] = None
        current_segment_head: Optional[EntityBuilder] = None
        queued_attach: List[EntityBuilder] = []
        connectors: List[EntityBuilder] = []
        pending_segment_connectors: List[EntityBuilder] = []

        step_size = max(1, len(connections) - 1)
        next_hidden_tick_beat = math.floor(float(connections[0].get("beat", 0)) * 2 + 1) / 2

        for step_idx, conn in enumerate(connections):
            conn_type = conn.get("type", "")
            beat = float(conn.get("beat", 0))
            lane = float(conn.get("lane", 0)) if "lane" in conn else 0.0
            size = float(conn.get("size", 1)) if "size" in conn else 0.0
            judge_type = conn.get("judgeType", "normal")
            conn_critical = bool(conn.get("critical", slide_critical))
            ease_value = _CONNECTOR_EASES.get(conn.get("ease", "linear"), 1)

            is_sim_eligible = False
            is_attached = False
            name_parts: List[str] = []

            if conn_type == "start":
                if judge_type == "none":
                    name_parts.append("Anchor")
                else:
                    name_parts.append("Critical" if conn_critical else "Normal")
                    name_parts.append("Head")
                    name_parts.append("Trace" if judge_type == "trace" else "Tap")
                    is_sim_eligible = True
            elif conn_type == "end":
                if judge_type == "none":
                    name_parts.append("Anchor")
                else:
                    name_parts.append("Critical" if conn_critical else "Normal")
                    name_parts.append("Tail")
                    direction = conn.get("direction")
                    if direction:
                        name_parts.append("TraceFlick" if judge_type == "trace" else "Flick")
                    elif judge_type == "trace":
                        name_parts.append("Trace")
                    else:
                        name_parts.append("Release")
                    is_sim_eligible = True
            elif conn_type == "tick":
                if "critical" in conn:
                    name_parts.append("Critical" if conn_critical else "Normal")
                    name_parts.append("Trace" if judge_type == "trace" else "Tick")
                else:
                    name_parts.append("Anchor")
            elif conn_type == "attach":
                is_attached = True
                if "critical" in conn:
                    name_parts.append("Critical" if conn_critical else "Normal")
                    name_parts.append("Tick")
                else:
                    name_parts.append("TransientHiddenTick")
            else:
                continue

            name_parts.append("Note")
            entity = EntityBuilder("".join(name_parts))
            entity.set("#BEAT", beat)
            entity.set("lane", lane)
            entity.set("size", size)
            entity.set(
                "direction",
                _DIRECTIONS.get(conn.get("direction"), 0)
                if conn.get("direction") and conn_type == "end"
                else 0,
            )
            entity.set("isAttached", 1 if is_attached else 0)
            entity.set("connectorEase", ease_value)
            entity.set("isSeparator", 0 if slide_type == "slide" else 1)
            entity.set("segmentKind", 2 if slide_critical else 1)
            entity.set(
                "segmentAlpha",
                1 - 0.8 * (step_idx / step_size) if slide_type != "slide" else 1,
            )
            entity.set("segmentLayer", 0 if slide_type == "slide" else 1)
            entity.set("#TIMESCALE_GROUP", get_tsg(int(conn.get("timeScaleGroup", 0))))
            all_entities.append(entity)

            if is_sim_eligible:
                sim_eligible.append(entity)

            if head_note is None:
                head_note = entity
            if current_segment_head is None:
                current_segment_head = entity
            entity.set("activeHead", head_note)

            if is_attached:
                queued_attach.append(entity)
            else:
                if prev_joint is not None:
                    for attach in queued_attach:
                        attach.set("attachHead", prev_joint)
                        attach.set("attachTail", entity)
                    queued_attach.clear()

                    while slide_type == "slide" and next_hidden_tick_beat + _FLOAT_TOLERANCE < beat:
                        hidden = EntityBuilder("TransientHiddenTickNote")
                        hidden.set("#BEAT", next_hidden_tick_beat)
                        hidden.set("#TIMESCALE_GROUP", get_tsg(0))
                        hidden.set("lane", lane)
                        hidden.set("size", size)
                        hidden.set("direction", _DIRECTIONS["up"])
                        hidden.set("isAttached", 1)
                        hidden.set("connectorEase", _CONNECTOR_EASES["linear"])
                        hidden.set("isSeparator", 0)
                        hidden.set("segmentKind", 1)
                        hidden.set("segmentAlpha", 0)
                        hidden.set("activeHead", head_note)
                        hidden.set("attachHead", prev_joint)
                        hidden.set("attachTail", entity)
                        all_entities.append(hidden)
                        next_hidden_tick_beat += 0.5

                    connector = EntityBuilder("Connector")
                    connector.set("head", prev_joint)
                    connector.set("tail", entity)
                    connectors.append(connector)
                    pending_segment_connectors.append(connector)
                    all_entities.append(connector)
                prev_joint = entity

            if slide_type != "slide":
                for connector in pending_segment_connectors:
                    connector.set("segmentHead", current_segment_head)
                    connector.set("segmentTail", entity)
                pending_segment_connectors.clear()
                current_segment_head = entity

            if prev_note is not None:
                prev_note.set("next", entity)
            prev_note = entity

        if not head_note or not prev_joint:
            continue

        if current_segment_head is not None:
            for connector in pending_segment_connectors:
                connector.set("segmentHead", current_segment_head)
                connector.set("segmentTail", prev_joint)

        if slide_type == "slide":
            for connector in connectors:
                connector.set("activeHead", head_note)
                connector.set("activeTail", prev_joint)

    # --- SimLine generation ---
    sim_eligible.sort(key=lambda e: (e.beat(), float(e.values.get("lane", 0))))
    sim_groups: List[List[EntityBuilder]] = []
    current_group: List[EntityBuilder] = []
    for note in sim_eligible:
        if not current_group or _nearly_equal(note.beat(), current_group[0].beat(), _SIMLINE_TOLERANCE):
            current_group.append(note)
        else:
            sim_groups.append(current_group)
            current_group = [note]
    if current_group:
        sim_groups.append(current_group)

    for group in sim_groups:
        group.sort(key=lambda e: float(e.values.get("lane", 0)))
        for j in range(len(group) - 1):
            sim = EntityBuilder("SimLine")
            sim.set("left", group[j])
            sim.set("right", group[j + 1])
            all_entities.append(sim)

    # --- Serialize entities ---
    entity_names: Dict[EntityBuilder, str] = {}
    counter = 0

    def get_name(entity: EntityBuilder) -> str:
        nonlocal counter
        if entity not in entity_names:
            entity_names[entity] = format(counter, "x")
            counter += 1
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
    """Serialize LevelData to gzipped JSON bytes with stable output."""
    json_bytes = json.dumps(leveldata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(json_bytes, mtime=0)


def sha1_hex(data: bytes) -> str:
    """Return the SHA-1 hex digest."""
    return hashlib.sha1(data).hexdigest()


def leveldata_blob(leveldata: Dict[str, Any]) -> Tuple[bytes, str]:
    """Return (gzipped bytes, SHA-1 hex) for a LevelData dict."""
    raw = serialize_leveldata(leveldata)
    return raw, sha1_hex(raw)
