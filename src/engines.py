"""Supported Sonolus engines and their bundled resource packs."""

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class EngineProfile:
    title: str
    filename: str
    item_name: str
    level_prefix: str


DEFAULT_ENGINE = "nextrush"
ENGINE_PROFILES = {
    "nextrush": EngineProfile("NextRUSH+", "engine.scp", "NextRUSH_P", "om2usc"),
    "next-sekai": EngineProfile(
        "Next SEKAI", "engine_next_sekai.scp", "coconut-next-sekai-1", "om2usc-next-sekai"
    ),
}


def get_engine_profile(target_engine: str) -> EngineProfile:
    try:
        return ENGINE_PROFILES[target_engine]
    except KeyError:
        raise ValueError(f"Unsupported target engine: {target_engine}") from None


def default_engine_path(target_engine: str = DEFAULT_ENGINE) -> Path:
    profile = get_engine_profile(target_engine)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / profile.filename
