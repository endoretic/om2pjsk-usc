---
name: nextrush-upstream-sync
description: "Synchronize this project with upstream NextRUSH+ updates. Use when Codex needs to check the latest UntitledCharts/sonolus-next-rush-engine tag or commit, decide whether upstream USC-to-LevelData converter changes must be ported into src/nextrush_leveldata.py, rebuild or repack engine.scp from upstream build/dist/engine runtime blobs, update agent docs, or smoke-test the bundled NextRUSH+ engine resource."
---

# NextRUSH+ Upstream Sync

## Scope

Use this skill when syncing this repository with upstream NextRUSH+:
<https://github.com/UntitledCharts/sonolus-next-rush-engine>

In scope:
- Verify the latest upstream tag/commit.
- Compare upstream `js/src/usc` against the previously bundled/checked version.
- Decide whether `src/nextrush_leveldata.py` needs code changes.
- Build or obtain upstream engine runtime blobs.
- Repack repository-root `engine.scp`.
- Update project agent docs with the bundled upstream version.
- Run CLI smoke checks against the current `engine.scp`.

Out of scope:
- Changing osu!mania parsing or lane mapping unless upstream USC semantics require it.
- Unrelated skin/background/effect/particle replacements. A demonstrated runtime/skin incompatibility must be fixed as part of the sync or bug fix.
- Treating release notes as authoritative without checking source diffs.

## Upstream Check

Never assume the latest version from memory. Always verify:

```bash
git ls-remote --heads --tags https://github.com/UntitledCharts/sonolus-next-rush-engine.git
```

Clone or update a temporary upstream checkout under `.tmp/`, for example:

```bash
git clone --depth 300 https://github.com/UntitledCharts/sonolus-next-rush-engine.git .tmp/nr-upstream-history
git -C .tmp/nr-upstream-history fetch --tags --depth 500
```

Inspect the latest tag and recent commits:

```bash
git -C .tmp/nr-upstream-history log --oneline --decorate -n 80
git -C .tmp/nr-upstream-history show --no-patch --format="%H%n%ad%n%s" --date=iso <latest-tag>
```

## Converter Sync Decision

The local LevelData converter is `src/nextrush_leveldata.py`, ported from upstream `js/src/usc`.

Before editing converter code, diff upstream USC files:

```bash
git -C .tmp/nr-upstream-history diff --name-status <old-tag>..<latest-tag> -- js/src/usc
git -C .tmp/nr-upstream-history diff <old-tag>..<latest-tag> -- js/src/usc/convert.ts js/src/usc/index.ts
```

Rules:
- If `js/src/usc` has no diff, do not edit `src/nextrush_leveldata.py` for engine runtime-only changes.
- If `js/src/usc/index.ts` changes schema fields that this project emits, update `src/osu_to_usc.py` or docs as needed.
- If `js/src/usc/convert.ts` changes entity graph generation, port the relevant subset into `src/nextrush_leveldata.py`.
- The LevelData converter is shared with Next SEKAI. Validate changes against both bundled runtimes, without changing the internal USC dialect.

## Engine Runtime Sync

`engine.scp` is a complete Sonolus package. Preserve compatible bundled default resources, but check skin compatibility against the selected runtime before carrying an old skin forward. Matching item names or valid SHA-1 hashes do not prove compatibility: sprite names, number groups, and transforms can change without an item rename.

Upstream release pages may have no direct `.scp` asset. Prefer these sources, in order:
1. GitHub Actions `next-rush-engine` artifact matching the latest tag SHA, if accessible.
2. A local upstream build with `sonolus-py build`.

If building locally, read the selected upstream revision's `pyproject.toml`, `uv.lock`, and `.github/workflows/build.yml` first. Use its own environment and locked dependencies, not this application's GUI environment. For example, upstream v2.16.3 requires Python >=3.14 and `sonolus-py~=1.2.5`; the older 0.16.0 build instructions are not compatible.

For v2.16.3, the upstream workflow sets `NEXT_RUSH_SKIP_SERVER_RESOURCES=1` to avoid downloading development-only server resources:

```powershell
Push-Location .tmp/nr-upstream-history
uv sync --locked --python 3.14
$env:NEXT_RUSH_SKIP_SERVER_RESOURCES = "1"
uv run sonolus-py build
Remove-Item Env:NEXT_RUSH_SKIP_SERVER_RESOURCES
Pop-Location
```

Build output should include:

```text
build/dist/engine/EngineConfiguration
build/dist/engine/EnginePlayData
build/dist/engine/EngineWatchData
build/dist/engine/EnginePreviewData
build/dist/engine/EngineTutorialData
build/dist/engine/EngineRom
```

Build the pinned upstream source with a supported Python version. Do not patch its annotations to force a build with an older interpreter. Record the exact tag and commit SHA; tags and release timestamps alone are not enough to identify the source used.

## Repack `engine.scp`

Use the bundled helper after `build/dist/engine` exists:

```bash
python .github/skills/nextrush-upstream-sync/scripts/repack_engine_scp.py \
  --engine-scp engine.scp \
  --dist-engine .tmp/nr-upstream-history/build/dist/engine \
  --upstream-version v2.16.3 \
  --upstream-commit 6d6dd372985cd35154282129b4031adc9874b615
```

The script:
- Replaces only engine runtime SRLs: configuration, playData, watchData, previewData, tutorialData, and rom.
- Updates `sonolus/engines/NextRUSH_P`, `sonolus/engines/list`, and `sonolus/engines/info`.
- Preserves non-engine resources unless `--skin-scp` explicitly requests the same default skin from another pack.
- Validates that every engine runtime hash points to an existing `sonolus/repository/<sha1>` blob and matches the blob bytes.

### Default Skin Compatibility

The v2.16.3 runtime expects `Judge Perfect`/`Judge Great` and other `Judge ...` sprites, plus `UI Number 0` through `17`. The legacy bundled skin used unprefixed judgment names, only 12 UI number sprites, and extra Combo label transforms (about 2.67x width). Do not reuse that skin with the new runtime.

The corrected `NR-V3-S1-EN` skin was fetched from `https://untitledcharts.com` on 2026-10-22: data SHA-1 `0b4aec47e0efb34c745b45f752a52efd406de5ac`, texture SHA-1 `60c73d46ffe3568c2b524bd8b89f0c870819a078`.

To refresh only that skin while retaining a pinned engine build:

```bash
python scripts/fetch_engine_pack.py --server https://untitledcharts.com --engine-name NextRUSH_P --out .tmp/nextrush-online.scp
python .github/skills/nextrush-upstream-sync/scripts/repack_engine_scp.py \
  --engine-scp engine.scp --dist-engine .tmp/nr-upstream-history/build/dist/engine \
  --upstream-version v2.16.3 --upstream-commit 6d6dd372985cd35154282129b4031adc9874b615 \
  --skin-scp .tmp/nextrush-online.scp
```

`--skin-scp` verifies the same skin name/source and its resource hashes, updates embedded and standalone skin references, and removes unreferenced old skin blobs. It does not import the downloaded engine runtime. Compare all six runtime hashes before and after a skin-only repair.

Do not overwrite `engine.scp` with the online snapshot blindly. During this fix the official server advertised v2.12.5, older than our pinned v2.16.3; a client-side update could replace both skin and engine. A successful client update alone does not isolate which resource fixed a visual problem.

## Documentation Updates

After repacking, update project docs that mention the bundled engine version:
- `AGENTS.md` -> "Updating NextRUSH+ Engine Resources"
- Any skill or agent reference that names the current bundled upstream version

Do not add volatile commit-history summaries to README unless the user asks.

## Validation

Run these checks before finishing:

```bash
python -c "import json, zipfile; z=zipfile.ZipFile('engine.scp'); e=json.loads(z.read('sonolus/engines/NextRUSH_P'))['item']; print(e['description'])"
python osu_mania_to_scp.py testdata/dan.osz --engine engine.scp --out .tmp/engine-check.scp --single-difficulty "~ 10th ~ (Marathon)"
```

Run the automated tests for both targets:

```bash
python -m unittest discover -s tests -v
```

Also smoke-test `--target-engine next-sekai` after shared converter changes. Distinguish these local checks from real Sonolus import/gameplay validation.

For skin changes, import a newly generated package without updating it online first and verify judgment text, Combo, score/life bars, and pause/skip controls in the client. Offline sprite-contract tests cannot prove the rendered layout is correct on a device.
