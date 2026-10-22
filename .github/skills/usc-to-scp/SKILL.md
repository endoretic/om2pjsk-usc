---
name: usc-to-scp
description: "Package the project's USC JSON and associated resources into Sonolus .scp packages for NextRUSH+ or Next SEKAI. Use when converting USC to native LevelData, selecting target engine resources, building repository blobs/SRLs, constructing levels/list/details/info/package documents, validating imports, or debugging resource packaging."
---

# USC -> SCP Packaging

## Scope

Use this skill after USC JSON exists.

In scope:
- Convert the project's USC JSON to shared NextRUSH+ / Next SEKAI LevelData.
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
- Engine profiles: `src/engines.py`
- Engine resources: `engine.scp`, `engine_next_sekai.scp`
- Importable examples: `testdata/Next_Insane.scp`, `testdata/guide.scp`
- Official Sonolus resource rules: <https://wiki.sonolus.com/custom-server-specs/misc/resources>
- Official LevelItem schema: <https://wiki.sonolus.com/custom-server-specs/misc/level-item>
- Official BackgroundItem schema: <https://wiki.sonolus.com/custom-server-specs/misc/background-item>
- Upstream packer behavior: <https://github.com/Sonolus/sonolus-pack>
- NextRUSH+ USC converter: <https://github.com/UntitledCharts/sonolus-next-rush-engine/tree/master/js/src/usc>
- Next SEKAI source: <https://github.com/Next-SEKAI/sonolus-next-sekai-engine>

## Pipeline

```
Project USC JSON -> shared native LevelData -> gzipped LevelData blob
resources -> sonolus/repository/<sha1>
metadata -> sonolus/levels/list + sonolus/levels/<name> + info/package docs
all entries -> .scp ZIP
```

## Engine Selection

Use `src/engines.py` to choose the bundled pack and expected engine item:
- `nextrush`: `engine.scp` / `NextRUSH_P`.
- `next-sekai`: `engine_next_sekai.scp` / `coconut-next-sekai-1`.

Derive default resources from the selected engine item, not a hard-coded background name. Use the profile's distinct level/background prefix so imports for the two targets can coexist. Reject a custom pack if its engine identifier does not match the selected target.

Keep the internal USC in the NextRUSH+ dialect. Next SEKAI's official USC converter expects a different schema; the project instead generates the shared native LevelData subset directly. Test emitted entities and imported fields against both bundled runtimes.

## Slide/Hold Conversion

For USC `slide` objects, follow the upstream NextRUSH+ `uscToLevelData` entity graph:
- Use each connection's own `critical` and `judgeType` to choose Head/Tail archetypes.
- Release tails are `NormalTailReleaseNote` / `CriticalTailReleaseNote`; trace tails are `NormalTailTraceNote` / `CriticalTailTraceNote`; `judgeType: "none"` tails become unjudged `AnchorNote`.
- Generate `Connector` entities between slide joints, set `activeHead` / `activeTail`, and generate transient hidden ticks between long hold endpoints.
- Hidden ticks follow the `0.5`-beat grid strictly between endpoints, without an additional exclusion window after the head.
- Do not collapse holds to only a head note plus tail note; that loses the active connector structure the engine expects.

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

Generated osu backgrounds are local items: remove the template's `source` and `authorUser` before replacing `name`, display text, and SRLs. `source` is an online update address, not attribution. Inheriting the engine server's address can cause collection updates to replace every generated image with that server's fallback background. Keep `source` only on unmodified upstream resources that actually exist on that server.

## Package Structure

Write at least:
- `sonolus/package`
- `sonolus/info`
- `sonolus/levels/info`
- `sonolus/levels/list`
- `sonolus/levels/<level_name>`
- copied engine/skin/background/effect/particle docs from the selected engine pack
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
