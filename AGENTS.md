# Project Guidelines

## Architecture

**om2usc** — Osu!Mania beatmaps → Project Sekai-compatible USC → NextRUSH+ LevelData → Sonolus SCP.

Primary subsystem:
- **Converter** (`src/` + `osu_mania_to_scp.py`): Main pipeline — parse .osu, convert to USC, serialize LevelData, package .scp. Keep the conversion core reusable, but third-party dependencies are allowed when they materially improve GUI, packaging, media handling, or reliability.
- **Windows GUI** (`gui/` + `om2usc_gui.py`): PySide6 desktop app for batch import, progress display, export options, and background preview.

Detailed agent references live in `.github/skills/`:
- `osu-mania-to-usc/SKILL.md`: osu!mania `.osz/.osu` parsing and USC JSON generation only
- `osu-mania-to-usc/references/osu-mania-osu-syntax-notes.md`: .osu parsing details
- `usc-to-scp/SKILL.md`: USC/LevelData/resources to Sonolus `.scp` packaging
- `.github/agent-references/project-brief.md`: broader project history and full pipeline notes

### New Converter Module Layout

```
osu_mania_to_scp.py          # CLI entry point
src/
  osu_parser.py              # Parse .osu sections → OsuChart
  osu_to_usc.py              # OsuChart → USC JSON (BPM segments, beat conversion, lane mapping)
  nextrush_leveldata.py      # USC → NextRUSH+ LevelData (ported from upstream TS)
  scp_writer.py              # LevelData + engine.scp → output .scp (resource reuse, validation)
gui/
  app.py                     # PySide6 Windows GUI
om2usc_gui.py                # GUI launcher
```

### Pipeline

```
.osz (ZIP) → [osu_parser] → OsuChart → [osu_to_usc] → USC JSON → [nextrush_leveldata] → LevelData → [scp_writer] → .scp
```

## Windows GUI Direction

The next product target is a Windows desktop GUI on top of the existing converter.

UI goals:
- Win11-like acrylic / transparent / semi-transparent flat design
- subtle Japanese anime influence without sacrificing readability
- conversion progress bar and clear batch status
- after loading `.osz`, randomly choose one included background image for the window backdrop
- always protect text and primary controls from low-contrast or busy backgrounds with blur, dimming, scrims, or panel opacity

Functional goals:
- batch import multiple `.osz` packages
- configurable hold/slide tail judgment type: `release` or `trace` only
- optional Tinged Columns conversion: 4K lanes 1/4, 5K lanes 2/4, 6K lanes 2/5 become critical notes
- export mode: one `.scp` per `.osz`
- export mode: merge multiple `.osz` packages into one `.scp`
- selectable output path
- gameplay background option: original osu background resource or NextRUSH+ default background

## Implementation Status

### ✅ Completed
- **Phase 1**: .osz/.osu parsing — Mode:3 validation, TimingPoints (red/green), HitObjects (tap/hold), key count from CircleSize
- **Phase 2**: USC JSON generation — BPM segments, beat conversion (time→beat), lane/size mapping (12-unit stage), single/slide objects
- **Phase 4**: NextRUSH+ LevelData — EntityBuilder pattern, #BPM_CHANGE, #TIMESCALE_GROUP, note archetypes (NormalTapNote, NormalHeadTapNote, NormalTailReleaseNote), SimLine generation
- **Phase 5**: SCP packaging — engine resources (skins/effects/particles/repository), gzipped JSON resources, raw audio resources, PNG cover/background resources, levels list
- **Phase 6**: Multi-difficulty — all valid mania charts per .osz, placeholder filtering (≤1 note), `--single-difficulty` flag, BGM/cover dedup
- 4K/5K/6K all tested and verified
- Hold→slide conversion verified (lane, time, duration)
- Initial PySide6 Windows GUI implemented
- Batch export modes implemented: one `.scp` per `.osz`, or multiple `.osz` merged into one `.scp`
- Configurable hold tail style (`release` / `trace`) and gameplay background mode implemented
- Optional Tinged Columns conversion implemented for GUI/CLI (`--tinged-columns`)

### ❌ Pending
- Green-line SV (timeScale) mapping not tested with complex SV charts
- Original osu background as gameplay background is generated but still needs real Sonolus import validation
- No hitsound preservation
- 7K not implemented (only 4K/5K/6K for now)
- Packaged Windows executable not yet smoke-tested

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

### USC Lane/Size Mapping
USC `lane` is the note center on a 12-unit stage. USC `size` is the note half-width used by NextRUSH+, not the full spacing between lane centers.

```python
column_width = 12 / keyCount
lane = -6 + (col + 0.5) * column_width
size = column_width / 2
```

Use `testdata/key4.usc`, `testdata/key5.usc`, and `testdata/key6.usc` as minimal lane/size references.

### Tinged Columns
When enabled, convert objects on these 1-based mania lanes to USC `critical: true`:
- 4K: lanes 1 and 4 (`col` 0 and 3)
- 5K: lanes 2 and 4 (`col` 1 and 3)
- 6K: lanes 2 and 5 (`col` 1 and 4)

This applies to both tap `single` objects and hold `slide` objects. Keep it disabled by default.

### Dependency Policy
The stdlib-only restriction is removed. Prefer the best implementation result over avoiding dependencies.

Use third-party packages when they clearly improve the product, especially for:
- Windows GUI and acrylic/transparent visual effects
- image preview, resizing, format handling, and generated thumbnails
- packaging into a Windows desktop executable
- robust progress reporting, background workers, or async UI integration

Keep conversion logic reasonably isolated from GUI code so the CLI and automated validation remain usable. Document new runtime/build dependencies in the repo when adding them.

Likely acceptable dependencies include `PySide6` or another mature Windows-capable GUI toolkit, `Pillow` for image handling, and `PyInstaller`/`Nuitka` for executable packaging.

### Sonolus Resource Packaging
Follow Sonolus resource types, not a blanket ".scp = gzip" rule:
- SRL `hash` is the SHA1 of the exact bytes stored in `sonolus/repository/<hash>`.
- JSON resources such as LevelData, background data, and configuration are gzip-compressed JSON before hashing/storing.
- Binary schema resources such as engine ROM are gzip-compressed before hashing/storing.
- Image resources are raw image bytes, preferably PNG. Convert osu JPG/WebP backgrounds to PNG for level covers and gameplay backgrounds.
- Audio resources are raw audio bytes, preferably MP3. Do not gzip BGM/preview.
- Archive resources are raw ZIP bytes. Do not gzip effect audio archives.
- `LevelItem.version` is `1`; `BackgroundItem.version` is `2`.
- `sonolus/levels/<name>` is a level details document and must include `item`, `description`, `actions`, `hasCommunity`, `leaderboards`, and `sections`.

### Updating NextRUSH+ Engine Resources
`engine.scp` is the bundled NextRUSH+ resource pack used when creating output packages. To update it:
1. Get a newer compatible NextRUSH+ Sonolus `.scp` resource pack from the upstream project or its release/build output.
2. Replace the repository-root `engine.scp`.
3. Confirm the package still contains `sonolus/engines/NextRUSH_P`; otherwise update `src/scp_writer.py` before converting.
4. Run a smoke conversion, for example `python osu_mania_to_scp.py testdata/4K.osz --engine engine.scp --out .tmp/engine-check.scp`, then inspect/import the result.

### Offset Sign
Use the first red TimingPoint as USC beat 0, and set `usc.offset = first_red_time_ms / 1000`. This places beat 0 at the original `.osu` audio timestamp after converting HitObject times to beats.

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

# Merge multiple .osz files
python osu_mania_to_scp.py testdata/4K.osz testdata/5K.osz --engine engine.scp \
    --out merged.scp --merge --tail-mode trace --background-mode original --tinged-columns
```

### GUI Usage
```bash
python -m pip install -r requirements.txt
python om2usc_gui.py

# Optional Windows executable build
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

### Test Data
- `testdata/4K.osz`, `testdata/5K.osz`, `testdata/6K.osz` — input beatmaps
- `engine.scp` — NextRUSH+ resource pack
- `testdata/Next_Insane.usc` — reference USC format
- `testdata/Next_Insane.scp` — reference SCP with complex LevelData
