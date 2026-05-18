---
name: osu-mania-to-usc
description: "Convert osu!mania .osz beatmaps to USC JSON and Sonolus SCP packages. Use when: parsing .osu files, building USC charts, converting USC to NextRUSH+ LevelData, packaging .scp files, or debugging the osu!mania → Sonolus pipeline."
---

# osu!mania → USC → SCP Conversion

## Pipeline Overview

```
.osz (ZIP) → .osu (text) → internal model → USC JSON → LevelData (entity graph) → .scp (ZIP+gzip)
```

## Key References
- Full spec & plan: `references/project-brief.md`
- Parsing rules: `references/osu-mania-osu-syntax-notes.md`
- Test data: `testdata/4K.osz`, `5K.osz`, `6K.osz`, `Next_Insane.usc`, `Next_Insane.scp`
- Upstream NextRUSH+ converter: <https://github.com/UntitledCharts/sonolus-next-rush-engine/tree/main/js/src/usc>

## Conversion Rules

### Lane Calculation — ALWAYS floor()
```python
col = floor(x * keyCount / 512)
col = max(0, min(keyCount - 1, col))
```

### USC Lane/Size Mapping (stage width = 12)
```python
column_width = 12 / keyCount
lane = -6 + (col + 0.5) * column_width
size = column_width
```

### BPM from Red TimingPoints
```python
BPM = 60000 / beatLength
first_red_time_ms → beat 0
```

### SV from Green TimingPoints
```python
timeScale = 100 / abs(beatLength)
```

### HitObject Types
- `type & 1 != 0` → tap → USC `single`
- `type & 128 != 0` → hold → USC `slide` (start/end connections)
- Hold `endTime` is in `objectParams` as `endTime:hitSample`

### Offset (UNRESOLVED)
`usc.offset` sign not validated. Always mark with `# TODO: verify offset sign in Sonolus`.

## Procedure

### Step 1: Parse .osz
```python
entries = read_zip(osz_path)
osu_files = [p for p in entries if p.endswith('.osu')]
```

### Step 2: Parse .osu sections
See `references/osu-mania-osu-syntax-notes.md` for field details.
Key sections: `[General]`, `[Difficulty]`, `[TimingPoints]`, `[HitObjects]`, `[Events]`

### Step 3: Build timing model
Sort red TimingPoints by time. Build BPM segments. Implement `time_ms_to_beat()`.

### Step 4: Generate USC
Create `bpm`, `timeScaleGroup`, `single`, `slide` objects.

### Step 5: Convert to LevelData
Port NextRUSH+ `uscToLevelData()` logic. Use entity builder pattern.

### Step 6: Package SCP
Embed engine.scp resources. Write LevelData + BGM + cover. Validate repository references.
