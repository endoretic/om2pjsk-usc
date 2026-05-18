---
name: usc-to-scp
description: "Package USC JSON charts and associated resources into Sonolus .scp packages for NextRUSH+. Use when Codex needs to convert USC to NextRUSH+ LevelData, build Sonolus repository blobs/SRLs, attach BGM/cover/background resources, construct levels/list/details/info/package documents, validate SCP imports, or debug Sonolus resource packaging after USC JSON already exists."
---

# USC -> SCP Packaging

## Scope

Use this skill after USC JSON exists.

In scope:
- Convert USC JSON to NextRUSH+ LevelData.
- Package LevelData, BGM, cover, preview, background, and engine resources.
- Build Sonolus `.scp` ZIP entries.
- Validate repository references and level details documents.
- Debug Sonolus import errors related to resource packaging or details endpoints.

Out of scope:
- Parsing osu `.osu` syntax.
- Mapping osu!mania columns to USC lanes.
- Deciding osu timing/SV conversion rules.

Use `osu-mania-to-usc` for the osu!mania -> USC stage.

## References

- Local packer: `src/scp_writer.py`
- Local LevelData converter: `src/nextrush_leveldata.py`
- Engine resources: `engine.scp`
- Importable examples: `testdata/Next_Insane.scp`, `testdata/guide.scp`
- Official Sonolus resource rules: <https://wiki.sonolus.com/custom-server-specs/misc/resources>
- Official LevelItem schema: <https://wiki.sonolus.com/custom-server-specs/misc/level-item>
- Official BackgroundItem schema: <https://wiki.sonolus.com/custom-server-specs/misc/background-item>
- Upstream packer behavior: <https://github.com/Sonolus/sonolus-pack>
- NextRUSH+ USC converter: <https://github.com/UntitledCharts/sonolus-next-rush-engine/tree/main/js/src/usc>

## Pipeline

```
USC JSON -> NextRUSH+ LevelData -> gzipped LevelData blob
resources -> sonolus/repository/<sha1>
metadata -> sonolus/levels/list + sonolus/levels/<name> + info/package docs
all entries -> .scp ZIP
```

## Resource Rules

The SRL `hash` is the SHA-1 of the exact bytes stored at `sonolus/repository/<hash>`.

Compress only resource types that require compression:
- JSON resources: serialize as UTF-8 JSON, gzip, then hash/store. This includes LevelData, background data, and background configuration.
- Binary schema resources such as engine ROM: gzip, then hash/store.

Do not gzip these resource types:
- Images: store raw image bytes. Prefer PNG.
- Audio: store raw audio bytes. Prefer MP3 for BGM and preview.
- Archives: store raw ZIP bytes, for example effect audio archives.

For osu-derived images:
- Convert JPG/WebP/etc. to PNG before using as Sonolus image resources.
- Use a small square PNG as level `cover`.
- Use a separate PNG as gameplay background `image`.
- Create background `data` and `configuration` as gzipped JSON resources.

## Required Level Documents

Each `sonolus/levels/<name>` entry is a level details document. It must include:

```json
{
  "item": {},
  "description": "",
  "actions": [],
  "hasCommunity": false,
  "leaderboards": [],
  "sections": []
}
```

Writing only `{"item": ...}` can import package resources but fail with "failed to load level details".

## LevelItem Rules

Use `version: 1`.

Required item fields include:
- `name`
- `version`
- `rating`
- `title`
- `artists`
- `author`
- `tags`
- `engine`
- `useSkin`
- `useBackground`
- `useEffect`
- `useParticle`
- `cover`
- `bgm`
- `data`

`preview` is optional but should reuse `bgm` when no separate preview clip exists.

The local package format embeds full item dictionaries for `engine` and non-default `useBackground.item`, matching the existing importable examples.

## BackgroundItem Rules

Use `version: 2`.

Required resource fields:
- `thumbnail`: PNG SRL
- `data`: gzipped JSON SRL
- `image`: PNG SRL
- `configuration`: gzipped JSON SRL

Typical generated background data:

```json
{"aspectRatio":1.777778,"fit":"cover","color":"#000000"}
```

Typical generated background configuration:

```json
{"blur":0,"mask":"#0000"}
```

If using an engine-provided background template, preserve compatible fields such as `source`, then replace `name`, display text, and SRLs.

## Package Structure

Write at least:
- `sonolus/package`
- `sonolus/info`
- `sonolus/levels/info`
- `sonolus/levels/list`
- `sonolus/levels/<level_name>`
- copied engine/skin/background/effect/particle docs from `engine.scp`
- all referenced `sonolus/repository/<hash>` blobs

Use `sonolus/package`:

```json
{"shouldUpdate":false}
```

Use `sonolus/levels/info` with `sections`, not only title/subtitle.

## Validation

Before considering a package fixed:
- Confirm every `/sonolus/repository/<hash>` URL points to an existing repository entry.
- Confirm each repository filename equals SHA-1 of its stored bytes.
- Confirm BGM/preview are not gzip.
- Confirm cover/background images are PNG when generated from osu backgrounds.
- Confirm LevelData and background JSON resources are gzip.
- Confirm every level details document contains the six required top-level fields.
- Compare with `testdata/Next_Insane.scp` and `testdata/guide.scp` when import behavior differs.
