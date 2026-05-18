---
name: osu-mania-to-usc
description: "Convert osu!mania .osz/.osu beatmaps into USC JSON only. Use when Codex needs to parse osu!mania files, validate Mode:3 charts, extract timing/audio/background metadata, map mania columns to USC lanes, generate BPM/timeScaleGroup/single/slide USC objects, or debug the osu!mania to USC stage before any Sonolus SCP packaging."
---

# osu!mania -> USC

## Scope

Use this skill only for the osu!mania input and USC output boundary.

In scope:
- Read `.osz` ZIPs and `.osu` files.
- Parse osu sections and metadata.
- Validate osu!mania charts (`Mode: 3`).
- Convert taps/holds and timing data to USC JSON.
- Dump or inspect USC for correctness.

Out of scope:
- Converting USC to NextRUSH+ LevelData.
- Building `sonolus/repository` resources.
- Creating `.scp` packages.
- Debugging Sonolus import/resource packaging.

Use `usc-to-scp` for everything after USC JSON exists.

## References

- Parsing rules: `references/osu-mania-osu-syntax-notes.md`
- Local parser/converter: `src/osu_parser.py`, `src/osu_to_usc.py`
- CLI entry point: `osu_mania_to_scp.py`
- Test input: `testdata/4K.osz`, `testdata/5K.osz`, `testdata/6K.osz`
- Minimal lane/size references: `testdata/key4.usc`, `testdata/key5.usc`, `testdata/key6.usc`
- USC reference shape: `testdata/Next_Insane.usc`

## Conversion Rules

### Chart Filtering

Only accept valid osu!mania charts:
- `[General] Mode: 3`
- `CircleSize` gives `keyCount`.
- Ignore placeholder charts with too few notes.
- Support 4K/5K/6K currently; 7K remains out of scope unless implementation support is added.

### Lane Calculation

Always use `floor()`, never `round()`.

```python
col = floor(x * keyCount / 512)
col = max(0, min(keyCount - 1, col))
```

### USC Lane/Size Mapping

The USC stage width is 12.

```python
column_width = 12 / keyCount
lane = -6 + (col + 0.5) * column_width
size = column_width / 2
```

`lane` is the note center. USC `size` is the note half-width used by NextRUSH+, not the full spacing between adjacent lane centers.

### Timing

Red TimingPoints define BPM:

```python
bpm = 60000 / beatLength
```

The first red TimingPoint is beat 0. Build a timing model with `time_ms_to_beat()`.

Green TimingPoints map to USC timeScale changes:

```python
timeScale = 100 / abs(beatLength)
```

Use tolerance comparisons for TimingPoint times, for example `abs(a - b) < 1e-6`; never rely on exact float equality.

### HitObjects

- `type & 1 != 0`: tap -> USC `single`.
- `type & 128 != 0`: hold -> USC `slide`.
- Hold `endTime` is stored in `objectParams` as `endTime:hitSample`.
- Converted hold/slide tail judgment type is controlled by product config and currently only supports `release` or `trace`.
- Optional Tinged Columns config may convert specific lanes to USC `critical: true`: 4K lanes 1/4, 5K lanes 2/4, 6K lanes 2/5. These lane numbers are 1-based from left to right.
- Tinged Columns applies to both tap `single` objects and hold `slide` objects, and must stay disabled by default.

### Offset

`usc.offset` sign is unresolved against real Sonolus import. Keep the existing TODO marker and do not treat either sign as final without client validation.

## Output

Generate USC JSON with:
- `offset`
- `objects`
- `bpm` objects
- one default `timeScaleGroup` and SV-derived changes when present
- `single` notes for taps
- `slide` notes for holds with start/end connections

Do not write `.scp` packaging rules into this skill.
