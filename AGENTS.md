# Project Guidelines

## Architecture

**om2usc** — osu!mania beatmaps (.osz) → USC JSON → Sonolus LevelData → SCP package converter.

Primary subsystem:
- **Converter** (`src/` + `osu_mania_to_scp.py`): Main pipeline — parse .osu, convert to USC, serialize LevelData, package .scp. **Stdlib only**.

Detailed agent references live in `.github/skills/osu-mania-to-usc/`:
- `SKILL.md`: compact workflow and critical rules
- `references/project-brief.md`: full spec and conversion pipeline
- `references/osu-mania-osu-syntax-notes.md`: .osu parsing details

### New Converter Module Layout

```
osu_mania_to_scp.py          # CLI entry point
src/
  osu_parser.py              # Parse .osu sections → OsuChart
  osu_to_usc.py              # OsuChart → USC JSON (BPM segments, beat conversion, lane mapping)
  nextrush_leveldata.py      # USC → NextRUSH+ LevelData (ported from upstream TS)
  scp_writer.py              # LevelData + engine.scp → output .scp (resource reuse, validation)
```

### Pipeline

```
.osz (ZIP) → [osu_parser] → OsuChart → [osu_to_usc] → USC JSON → [nextrush_leveldata] → LevelData → [scp_writer] → .scp
```

## Implementation Status

### ✅ Completed
- **Phase 1**: .osz/.osu parsing — Mode:3 validation, TimingPoints (red/green), HitObjects (tap/hold), key count from CircleSize
- **Phase 2**: USC JSON generation — BPM segments, beat conversion (time→beat), lane/size mapping (12-unit stage), single/slide objects
- **Phase 4**: NextRUSH+ LevelData — EntityBuilder pattern, #BPM_CHANGE, #TIMESCALE_GROUP, note archetypes (NormalTapNote, NormalHeadTapNote, NormalTailReleaseNote), SimLine generation
- **Phase 5**: SCP packaging — engine resources (skins/effects/particles/repository), LevelData gzip+SHA1, BGM/cover from .osz, levels list
- **Phase 6**: Multi-difficulty — all valid mania charts per .osz, placeholder filtering (≤1 note), `--single-difficulty` flag, BGM/cover dedup
- 4K/5K/6K all tested and verified
- Hold→slide conversion verified (lane, time, duration)

### ❌ Pending
- **Phase 3**: Validate `usc.offset` sign by importing a test .scp into real Sonolus
- Green-line SV (timeScale) mapping not tested with complex SV charts
- Background images only used as level cover; gameplay background uses engine default
- No hitsound preservation
- 7K not implemented (only 4K/5K/6K for now)

## Critical Conventions

### Lane Calculation — ALWAYS `floor()`, NEVER `round()`
```python
# Correct:
col = floor(x * keyCount / 512)
col = max(0, min(keyCount - 1, col))

# Wrong — off-by-one errors:
col = round(x * keyCount / 512)
```
See `.github/skills/osu-mania-to-usc/references/osu-mania-osu-syntax-notes.md` for all parsing rules.

### Python: Stdlib Only
No `pip install`, no `requirements.txt`. Use only `json`, `zipfile`, `gzip`, `math`, `hashlib`, `collections`, `pathlib`, `re`, `argparse`.

### Offset Sign — UNRESOLVED
`usc.offset` direction is not yet validated against real Sonolus import. Do NOT assume `+` or `-`. Currently using `-first_red_time_ms / 1000`. All offset code is marked with `# TODO: verify offset sign in Sonolus`.

### Float Tolerance for TimingPoints
Timing point times carry microsecond precision. Always use tolerance comparisons (e.g., `abs(t1 - t2) < 1e-6`), never `==`.

## Build and Test

### CLI Usage
```bash
# List charts in .osz
python osu_mania_to_scp.py testdata/4K.osz --list

# Dump USC JSON for inspection
python osu_mania_to_scp.py testdata/4K.osz --dump-usc output_dir

# Full conversion (all difficulties)
python osu_mania_to_scp.py testdata/4K.osz --engine engine.scp --out output.scp

# Single difficulty only
python osu_mania_to_scp.py testdata/4K.osz --engine engine.scp --out output.scp \
    --single-difficulty "(Jesen) Grin (Re:Work Edit) 1.08x (high)"
```

### Test Data
- `testdata/4K.osz`, `testdata/5K.osz`, `testdata/6K.osz` — input beatmaps
- `engine.scp` — NextRUSH+ resource pack
- `testdata/Next_Insane.usc` — reference USC format
- `testdata/Next_Insane.scp` — reference SCP with complex LevelData
