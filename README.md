# om2pjsk-usc

Convert Osu!Mania beatmaps into the Project Sekai-compatible USC dialect used by NextRUSH+, then package them as Sonolus `.scp` archives.

This project does not target every USC format. Its USC output is designed for the Project Sekai / NextRUSH+ chart model.

```text
.osz / .osu -> Osu!Mania parser -> Project Sekai USC -> NextRUSH+ LevelData -> Sonolus SCP
```

## Features

- Converts valid Osu!Mania charts from `.osz` packages.
- Supports 4K, 5K, and 6K charts.
- Converts taps to USC `single` objects and holds to USC `slide` objects.
- Supports `release`, `trace`, and `none` hold tail styles.
- Converts BPM segments and timing-based time scale groups.
- Supports optional Tinged Columns critical-note conversion.
- Supports optional sparse hidden ticks for dense long-note charts.
- Exports one `.scp` per `.osz`, or merges multiple `.osz` packages into one `.scp`.
- Provides a Windows GUI with drag-and-drop import, progress display, batch export options, and background preview.

## Installation

Requires Python 3.10 or newer.

```bash
python -m pip install -r requirements.txt
```

Runtime and build dependencies are listed in `requirements.txt`:

- `PySide6` for the Windows GUI
- `Pillow` for image conversion and preview handling
- `pyinstaller` for optional executable packaging

## Windows Build

Published Windows builds are available from the [Releases](../../releases) page.

Build a Windows executable with PyInstaller:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The build script bundles `engine.scp` and `icon/om2usc.ico` with the generated application.

## CLI Usage

List available Osu!Mania charts:

```bash
python osu_mania_to_scp.py chart.osz --list
```

Dump Project Sekai-compatible USC JSON:

```bash
python osu_mania_to_scp.py chart.osz --dump-usc output_usc
```

Convert one package to SCP:

```bash
python osu_mania_to_scp.py chart.osz --engine engine.scp --out output.scp
```

Convert one named difficulty:

```bash
python osu_mania_to_scp.py chart.osz --engine engine.scp --out output.scp --single-difficulty "Hard"
```

Merge multiple packages into one SCP:

```bash
python osu_mania_to_scp.py chart-a.osz chart-b.osz --engine engine.scp --out merged.scp --merge
```

Useful conversion options:

| Option | Description |
| --- | --- |
| `--tail-mode {none,release,trace}` | Hold tail judgment style. Defaults to `release`; `none` creates an unjudged slide endpoint. |
| `--background-mode {default,original}` | Use the NextRUSH+ default gameplay background or generated backgrounds from the source beatmap. |
| `--tinged-columns` | Mark configured columns as critical notes: 4K lanes 1/4, 5K lanes 2/4, 6K lanes 2/5. |
| `--sparse-hidden-ticks` | Generate slide body hidden ticks every 1.0 beat instead of every 0.5 beat. |
| `--out-dir DIR` | Output directory for batch conversion when not using `--merge`. |

## Project Layout

```text
osu_mania_to_scp.py          CLI entry point
om2usc_gui.py                GUI launcher
engine.scp                   Bundled NextRUSH+ engine resource pack
requirements.txt             Python dependencies
src/
  osu_parser.py              .osu section parser
  osu_to_usc.py              Osu!Mania chart to Project Sekai USC converter
  nextrush_leveldata.py      USC to NextRUSH+ LevelData converter
  scp_writer.py              Sonolus SCP packager
gui/
  app.py                     PySide6 GUI application
icon/
  om2usc.ico                 Application icon
scripts/
  build_windows.ps1          Windows packaging script
```

## Notes

- The bundled `engine.scp` is the NextRUSH+ resource pack used when packaging output SCP files.
- `engine.scp` can be replaced with a newer compatible NextRUSH+ SCP resource pack.
- 7K charts are not implemented.
- Hitsounds are not preserved.
- Complex SV charts and original-background gameplay mode need broader real-client validation.

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

- [osu!](https://osu.ppy.sh) for the beatmap format and community.
- [Sonolus](https://sonolus.com) for the rhythm game engine platform.
- [NextRUSH+](https://github.com/UntitledCharts/sonolus-next-rush-engine) for the target Sonolus engine.
