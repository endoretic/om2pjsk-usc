# om2pjsk-usc

Convert Osu!Mania beatmaps into Sonolus `.scp` archives for **NextRUSH+** or **Next SEKAI**.

The intermediate USC uses the Project Sekai / NextRUSH+ chart model, not generic USC or Next SEKAI's USC input dialect. Both targets receive native LevelData generated from this shared representation.

```text
.osz / .osu -> Osu!Mania parser -> Project Sekai USC -> LevelData -> target engine SCP
```

## Features

- Converts valid Osu!Mania charts from `.osz` packages.
- Supports 4K, 5K, and 6K charts.
- Converts taps to USC `single` objects and holds to USC `slide` objects.
- Supports `release`, `trace`, and `none` hold tail styles.
- Converts BPM segments and timing-based time scale groups.
- Supports optional Tinged Columns critical-note conversion.
- Selects NextRUSH+ or Next SEKAI, including each engine's default resources.
- Exports one `.scp` per `.osz`, or merges multiple `.osz` packages into one `.scp`.
- Provides a Windows GUI with drag-and-drop import, progress display, batch export options, and background preview.

## Installation

Requires `uv`; the project pins Python 3.13 and downloads it automatically when needed.

```bash
uv sync
```

Runtime and build dependencies are declared in `pyproject.toml` and locked in `uv.lock`:

- `PySide6` for the Windows GUI
- `Pillow` for image conversion and preview handling
- `pyinstaller` for optional executable packaging

## Windows Build

Published Windows builds are available from the [Releases](../../releases) page.

Build a Windows executable with PyInstaller:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The build script bundles both engine resource packs and `icon/om2usc.ico`. Distribute the entire `dist/om2usc/` folder, including `_internal/`.

## GUI Usage

```bash
uv run python om2usc_gui.py
```

Choose **Target engine** in the Conversion panel. The resource pack and default gameplay background switch with it; a compatible custom resource pack can also be selected.

## CLI Usage

List available Osu!Mania charts:

```bash
uv run python osu_mania_to_scp.py chart.osz --list
```

Dump Project Sekai-compatible USC JSON:

```bash
uv run python osu_mania_to_scp.py chart.osz --dump-usc output_usc
```

Convert one package with NextRUSH+ (the default target):

```bash
uv run python osu_mania_to_scp.py chart.osz --out output.scp
```

Convert with Next SEKAI:

```bash
uv run python osu_mania_to_scp.py chart.osz --target-engine next-sekai --out output.scp
```

Convert one named difficulty:

```bash
uv run python osu_mania_to_scp.py chart.osz --engine engine.scp --out output.scp --single-difficulty "Hard"
```

Merge multiple packages into one SCP:

```bash
uv run python osu_mania_to_scp.py chart-a.osz chart-b.osz --engine engine.scp --out merged.scp --merge
```

Useful conversion options:

| Option | Description |
| --- | --- |
| `--target-engine {nextrush,next-sekai}` | Target engine. Defaults to `nextrush`. |
| `--engine FILE` | Override the bundled resource pack for the selected target. |
| `--tail-mode {none,release,trace}` | Hold tail judgment style. Defaults to `release`; `none` creates an unjudged slide endpoint. |
| `--background-mode {default,original}` | Use the selected engine's default gameplay background or generated backgrounds from the source beatmap. |
| `--tinged-columns` | Mark configured columns as critical notes: 4K lanes 1/4, 5K lanes 2/4, 6K lanes 2/5. |
| `--out-dir DIR` | Output directory for batch conversion when not using `--merge`. |

## Project Layout

```text
osu_mania_to_scp.py          CLI entry point
om2usc_gui.py                GUI launcher
engine.scp                   Bundled NextRUSH+ engine resource pack
engine_next_sekai.scp        Bundled Next SEKAI engine resource pack
requirements.txt             Python dependencies
pyproject.toml               uv project and dependency declarations
uv.lock                      Exact resolved dependency versions
src/
  engines.py                 Target profiles and bundled resource paths
  osu_parser.py              .osu section parser
  osu_to_usc.py              Osu!Mania chart to Project Sekai USC converter
  nextrush_leveldata.py      Shared USC to LevelData converter
  scp_writer.py              Sonolus SCP packager
gui/
  app.py                     PySide6 GUI application
icon/
  om2usc.ico                 Application icon
scripts/
  build_windows.ps1          Windows packaging script
  fetch_engine_pack.py       Fetch and validate an online engine resource pack
```

## Notes

- Each target has its own bundled resource pack and distinct level identifiers, so both conversions can coexist in a Sonolus collection.
- Generated backgrounds have no online update source, preventing collection updates from replacing them with an engine server's fallback image. Existing affected packages must be regenerated and reimported.
- 7K charts are not implemented.
- Hitsounds are not preserved.
- Complex SV charts and original-background gameplay mode need broader real-client validation.

## License

MIT. See [LICENSE](LICENSE).

Engine notices are included in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Acknowledgements

- [osu!](https://osu.ppy.sh) for the beatmap format and community.
- [Sonolus](https://sonolus.com) for the rhythm game engine platform.
- [NextRUSH+](https://github.com/UntitledCharts/sonolus-next-rush-engine) and [Next SEKAI](https://github.com/Next-SEKAI/sonolus-next-sekai-engine) for the target Sonolus engines.
