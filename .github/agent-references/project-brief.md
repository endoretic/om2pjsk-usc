# osu!mania -> USC -> NextRUSH+ SCP 项目启动说明

日期：2026-05-18

本文用于维护一个 Python-first 转换项目：读取 osu!mania `.osz` / `.osu` 谱面，把谱面转换为 USC，再使用 NextRUSH+ 的 LevelData 规则生成可导入 Sonolus 的 `.scp` 包。当前实现以 Python converter 为核心，下一阶段允许在其上增加 Windows GUI、图像处理和打包脚本；不再限制为标准库。

## 目标范围

输入：

- `.osz` 包，实质是 zip。
- 包内一个或多个 `.osu` 文件。
- 对应音频、封面 / 背景图片等资源。

输出：

- 一个 `.scp` 包。
- 包内包含：
  - `sonolus/levels/list`
  - `sonolus/levels/<level_name>`
  - `sonolus/repository/<hash>` 资源文件
  - NextRUSH+ 引擎、皮肤、效果、粒子等必要资源
  - 由 `.osu` 转换得到的 NextRUSH+ LevelData

Windows GUI 目标：

- 面向 Windows 桌面应用交付。
- 视觉风格优先考虑 Win11 acrylic / 半透明 / 扁平化效果，并允许轻微日式动漫风。
- 支持批量导入 `.osz`、转换进度条、随机背景预览、导出路径选择。
- 支持 1 个 `.osz` 输出 1 个 `.scp`，也支持多个 `.osz` 合并输出为 1 个 `.scp`。
- 支持配置 hold/slide 结尾判定类型，目前只保留 `release` / `trace`，以及游玩背景使用原背景资源或 NextRUSH+ 默认背景。

推荐阶段目标：

1. 先生成 `.usc.json`，人工检查时间、轨道、长条。
2. 再把 USC 转成 NextRUSH+ LevelData。
3. 最后打包成 `.scp`。

不要依赖 Sonolus 客户端或引擎在导入时自动转换旧格式。静态 `.scp` 里应直接放入已经生成好的 NextRUSH+ LevelData。

## 重要参考文件

当前仓库内：

- `osu-mania-osu-syntax-notes.md`：osu!mania `.osu` 语法笔记。
- `testdata/4K.osz`：osu!mania 4K 测试包。
- `testdata/5K.osz`：osu!mania 5K 测试包。
- `testdata/6K.osz`：osu!mania 5K 测试包。
- `engine.scp`：当前项目打包用的 NextRUSH+ 引擎资源包。
- `testdata/Next_Insane.usc`：USC 复杂测试谱。
- `testdata/Next_Insane.scp`：含复杂 Next Sekai / NextRUSH+ LevelData 的 SCP 测试包。

上游 / 文档：

- osu `.osu` 格式文档：<https://osu.ppy.sh/wiki/en/Client/File_formats/osu_%28file_format%29>
- osu Circle Size：<https://osu.ppy.sh/wiki/en/Beatmap/Circle_size>
- osu offset：<https://osu.ppy.sh/wiki/en/Offset>
- osu local offset：<https://osu.ppy.sh/wiki/en/Offset/Local_offset>
- osu universal offset：<https://osu.ppy.sh/wiki/en/Offset/Universal_offset>
- NextRUSH+ 当前主要公开仓库：<https://github.com/UntitledCharts/sonolus-next-rush-engine>
- NextRUSH+ USC schema / converter 目录：<https://github.com/UntitledCharts/sonolus-next-rush-engine/tree/main/js/src/usc>
- PJSekai+ 参考仓库，通常不是新项目主依赖：<https://github.com/sevenc-nanashi/sonolus-pjsekai-engine-extended>
- SCP Repacker 历史外部参考，不是当前实现依赖：<https://github.com/endoretic/SCP-Repacker>
历史上见过的旧 NextRUSH+ 地址：

- <https://github.com/hyeon2006/sonolus-next-rush-plus-engine>

新项目应优先以 `UntitledCharts/sonolus-next-rush-engine` 为准。

## 4K.osz 观察结果

`4K.osz` 内包含多个 4K mania 谱面：

- 所有采样 `.osu` 均为 `Mode: 3`。
- `CircleSize: 4`，即 4K。
- 每个谱面一般配套一个 `.mp3` 和一个 `.jpg`。
- 存在一个类似 `delete this` 的非正式 / 占位谱面，只有 1 个 HitObject，后续应通过规则过滤。

解析 `.osz` 时要注意：

- `.osz` 是 zip。
- 跳过目录项。
- 文件名可能包含空格、括号、方括号和非 ASCII 字符。
- `.osu` 中的 `AudioFilename` 指向包内音频。
- 背景图通常在 `[Events]` 的 `Background` 行里。

## osu!mania 解析要点

必须读取的 section：

- `[General]`
- `[Metadata]`
- `[Difficulty]`
- `[TimingPoints]`
- `[HitObjects]`
- `[Events]`，用于背景图

关键字段：

- `Mode: 3`：mania 模式。
- `CircleSize`：mania 下等于 key 数。
- `AudioFilename`：音频文件名。
- `Title`、`Artist`、`Creator`、`Version`：用于 Sonolus level metadata。

HitObject 格式：

```text
x,y,time,type,hitSound,objectParams,hitSample
```

轨道计算：

```python
col = floor(x * key_count / 512)
col = max(0, min(key_count - 1, col))
lane_1_based = col + 1
```

必须使用 `floor`，不要用 `round`。

Tap：

- `type & 1 != 0`

Hold：

- `type & 128 != 0`
- mania hold 的 `objectParams` 第一段是 `endTime`：

```text
x,y,startTime,type,hitSound,endTime:hitSample
```

TimingPoint 格式：

```text
time,beatLength,meter,sampleSet,sampleIndex,volume,uninherited,effects
```

红线：

- `uninherited == 1`
- BPM = `60000 / beatLength`

绿线：

- `uninherited == 0`
- SV 倍率 = `100 / abs(beatLength)`

注意：

- `AudioLeadIn` 不是 BPM offset。
- 玩家 local offset / universal offset 不应该烘焙进谱面。

## USC 目标结构

NextRUSH+ USC 顶层结构：

```ts
{
  offset: number,
  objects: USCObject[]
}
```

核心对象：

- `bpm`
- `timeScaleGroup`
- `single`
- `slide`
- `guide`
- `damage`
- `skill`
- `feverChance`
- `feverStart`

新项目的 osu!mania MVP 只需要：

- `bpm`
- `timeScaleGroup`
- `single`
- `slide`

Tap -> `single`：

```json
{
  "type": "single",
  "beat": 0,
  "lane": 0,
  "size": 1,
  "critical": false,
  "trace": false,
  "timeScaleGroup": 0
}
```

Hold -> `slide`：

```json
{
  "type": "slide",
  "critical": false,
  "connections": [
    {
      "type": "start",
      "beat": 0,
      "lane": 0,
      "size": 1,
      "ease": "linear",
      "judgeType": "normal",
      "timeScaleGroup": 0
    },
    {
      "type": "end",
      "beat": 1,
      "lane": 0,
      "size": 1,
      "judgeType": "normal",
      "timeScaleGroup": 0
    }
  ]
}
```

## 时间转换

建议内部保留毫秒时间，再转换为 beat。

先按时间排序红线 TimingPoints，建立 BPM 段：

```text
segment_start_ms
beat_at_segment_start
beat_length_ms
bpm
```

某个 `time_ms` 转 beat：

```python
beat = segment.beat_at_start + (time_ms - segment.start_ms) / segment.beat_length_ms
```

建议把第一条红线作为 beat 0：

```text
first_red_time_ms -> beat 0
```

然后所有 BPM 对象也使用相对 beat：

```json
{ "type": "bpm", "beat": 0, "bpm": 180 }
```

高优先级待验证点：

- NextRUSH+ `uscToLevelData()` 会把 `usc.offset` 写入 `bgmOffset`。
- 对 osu 来说，`usc.offset` 的符号必须实测确认。
- 候选值：
  - `usc.offset = -first_red_time_ms / 1000`
  - 或 `usc.offset = first_red_time_ms / 1000`
- 不要在确认前把 offset 逻辑封死。先用一个很小的测试谱导入 Sonolus，确认第一个节拍和音乐是否对齐。

## 轨道与宽度映射

osu!mania 是离散轨道，NextRUSH+ / Prosekai 风格 LevelData 使用横向 `lane` 和 `size`。

建议先用固定舞台宽度 12：

```python
stage_width = 12
column_width = stage_width / key_count
lane = -stage_width / 2 + (col + 0.5) * column_width
size = column_width / 2
```

对于 4K：

```text
col 0 -> lane -4.5, size 1.5
col 1 -> lane -1.5, size 1.5
col 2 -> lane  1.5, size 1.5
col 3 -> lane  4.5, size 1.5
```

这不是 osu 原生显示，而是映射到 NextRUSH+ 判定线坐标。`lane` 是音符中心，`size` 是 NextRUSH+ 使用的半宽，不是相邻 lane 中心点之间的完整间距。最小参考见 `testdata/key4.usc`、`testdata/key5.usc`、`testdata/key6.usc`。

## SV / TimeScale 映射

osu!mania 绿线 SV 可初步映射到 USC `timeScaleGroup`：

```python
time_scale = 100 / abs(beatLength)
```

MVP 可以只生成一个 `timeScaleGroup`：

```json
{
  "type": "timeScaleGroup",
  "changes": [
    { "beat": 0, "timeScale": 1 }
  ]
}
```

如果存在绿线，则把绿线时间转换成 beat 后加入 changes：

```json
{
  "type": "timeScaleGroup",
  "changes": [
    { "beat": 0, "timeScale": 1 },
    { "beat": 16, "timeScale": 1.25 }
  ]
}
```

所有 `single` 和 `slide` connection 使用 `timeScaleGroup: 0`。

需要实测的问题：

- osu!mania 的实际滚速表现还受到玩家速度设置影响。
- 绿线映射到 NextRUSH+ `timeScale` 后，视觉变化是否符合预期需要用复杂 SV 谱验证。

## LevelData 生成

新项目应把 NextRUSH+ 的 `uscToLevelData()` 用 Python 复刻，而不是在 Python 中调用 Web 端 JS。

原则：

- 尽最大可能保持与上游 converter 一致。
- 常量名、archetype 名、字段名尽量贴近上游。
- 先只实现 osu!mania 会用到的对象：`bpm`、`timeScaleGroup`、`single`、`slide`。
- 复杂 guide / damage / skill / fever 可暂不实现。

NextRUSH+ converter 中的重要规则：

- USC `offset` 会写入 LevelData `bgmOffset`。
- 没有 BPM 时默认 BPM 160。
- 没有 timeScaleGroup 时默认 timeScale 1。
- `single` 会映射到 Tap / Flick / Trace 等 archetype。
- `slide` 会映射到 slide start / connector / end 相关 archetype。
- 同拍音符会自动生成 SimLine。

osu!mania 初期不需要：

- flick
- critical
- trace
- guide
- damage
- skill
- fever
- hitsound 独立资源

## SCP 打包结构

`.scp` 也是 zip 风格包。Sonolus 资源通常通过 SHA1 hash 放在：

```text
sonolus/repository/<sha1>
```

JSON 中引用资源通常类似：

```json
{
  "hash": "<sha1>",
  "url": "/sonolus/repository/<sha1>"
}
```

推荐从当前仓库 `engine.scp` 复制 NextRUSH+ 必要资源：

- `sonolus/engines/list`
- `sonolus/engines/<engine_name>`
- `sonolus/skins/list`
- `sonolus/skins/<skin_name>`
- `sonolus/effects/list`
- `sonolus/effects/<effect_name>`
- `sonolus/particles/list`
- `sonolus/particles/<particle_name>`
- 这些文件引用到的所有 `sonolus/repository/<hash>`

当前 `engine.scp` 中的目标引擎：

- `name`: `NextRUSH_P`
- `title`: `NextRUSH+`
- `source`: `https://untitledcharts.com`
- `version`: `13`

更新 NextRUSH+ 引擎资源的方式：

1. 从上游项目或其 release/build 输出获取新的兼容 NextRUSH+ Sonolus `.scp` 资源包。
2. 用新包替换仓库根目录的 `engine.scp`。
3. 确认新包仍包含 `sonolus/engines/NextRUSH_P`；如果引擎名变化，需要同步修改 `src/scp_writer.py` 中读取 engine item 的路径。
4. 用 `python osu_mania_to_scp.py testdata/4K.osz --engine engine.scp --out .tmp/engine-check.scp` 做一次打包冒烟测试，再导入 Sonolus 验证显示和游玩行为。

每个 level 需要：

- `sonolus/levels/<level_name>`
- `sonolus/levels/list` 中的 item
- LevelData blob
- BGM blob
- cover blob
- 可选 preview blob

Sonolus repository / SRL 规则：

- SRL `hash` 是 `sonolus/repository/<hash>` 中实际存储字节的 SHA1。
- LevelData、background data、background configuration 等 JSON resources：先 JSON UTF-8 序列化，再 gzip 压缩，再计算 SHA1 并写入 repository。
- Engine ROM 等 binary schema resources：gzip 压缩后计算 SHA1 并写入 repository。
- Image resources：原始图片字节写入 repository，不要 gzip。优先 PNG；来自 osu 的 JPG/WebP 背景应转成 PNG 后再作为 level cover / background image。
- Audio resources：原始音频字节写入 repository，不要 gzip。优先 MP3。
- Archive resources：原始 ZIP 字节写入 repository，不要 gzip。
- `LevelItem.version` 为 `1`；`BackgroundItem.version` 为 `2`。
- `sonolus/levels/<level_name>` 是 level details 文档，必须包含 `item`、`description`、`actions`、`hasCommunity`、`leaderboards`、`sections`。只写 `{"item": ...}` 会导致客户端加载 level details 失败。

资源建议：

- BGM：直接使用 `.osz` 内音频，按原始音频字节计算 SHA1。
- cover：使用 `[Events]` 里的背景图派生小尺寸 1:1 PNG cover。
- background：默认可使用 NextRUSH+ 默认 background。若要在游玩背景中显示 osu 背景图，需要创建 Sonolus `BackgroundItem`，并写入 PNG thumbnail/image、gzip 后的 background data/configuration，而不仅是 level cover。

## 建议项目结构

当前转换核心可以继续保持小模块；Windows GUI 应作为上层应用复用这些模块，而不是把转换逻辑写进界面事件里：

```text
osu-mania-usc-scp/
  README.md
  osu_mania_to_scp.py
  requirements.txt 或 pyproject.toml
  src/
    osu_parser.py
    osu_to_usc.py
    nextrush_leveldata.py
    scp_writer.py
  gui/
    app.py
    widgets.py
    workers.py
  testdata/
    4K.osz
    engine.scp
```

CLI 仍应保留，便于回归测试和批处理：

```text
osu_mania_to_scp.py
```

但建议内部仍按函数分层：

- `read_osz(path)`
- `parse_osu(text)`
- `build_timing_model(timing_points)`
- `time_ms_to_beat(time_ms)`
- `osu_to_usc(osu_chart)`
- `usc_to_nextrush_leveldata(usc)`
- `write_scp(output_path, levels, engine_pack)`
- `validate_repository_refs(entries)`

转换核心可继续使用的标准库：

- `argparse`
- `dataclasses`
- `gzip`
- `hashlib`
- `json`
- `math`
- `pathlib`
- `re`
- `zipfile`

允许使用第三方依赖，优先实现效果和工程可维护性：

- `PySide6`：优先候选 GUI 框架，适合做 Windows 桌面应用、半透明窗口、原生文件选择器、进度条和后台 worker。
- `Pillow`：用于读取 `.osz` 内背景图、生成预览图、缩放/转换图片格式、控制背景可读性。
- `PyInstaller` 或 `Nuitka`：用于打包 Windows 可执行文件。
- 其他依赖可以按实际效果引入，但需要记录用途，并避免让转换核心和 GUI 强耦合。

## CLI 建议

MVP：

```bash
python osu_mania_to_scp.py 4K.osz --engine engine.scp --out 4K.scp
```

建议参数：

```text
--engine engine.scp
--out output.scp
--dump-usc out_usc_dir
--single-difficulty "Version name"
--include-all
--skip-empty
--lane-width-scale 1.0
--offset-sign auto|positive|negative
--no-sv
```

## GUI 建议

当前 GUI 入口：

```bash
python -m pip install -r requirements.txt
python om2usc_gui.py
```

Windows 打包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

GUI 应继续复用 `src/` 下转换核心：

- `gui/app.py` 只负责界面、文件选择、随机背景预览和后台 worker。
- SCP 生成走 `src/scp_writer.py` 的 `build_scp()` / `build_merged_scp()`。
- 长条尾类型通过 `tail_mode` 传入 `src/osu_to_usc.py`，当前只支持 `release` / `trace`。
- 游玩背景通过 `background_mode` 传入 `src/scp_writer.py`。

## 分步 TODO

### Phase 1：解析 osz / osu

1. 新建 Python 项目和 CLI 入口。
2. 用 `zipfile` 读取 `.osz`，跳过目录项。
3. 收集 `.osu`、音频、图片文件。
4. 解码 `.osu`：
   - 优先 `utf-8-sig`
   - 失败后尝试 `utf-8`
   - 再失败尝试 `cp932` 或 `latin-1`
5. 解析 section 和 key-value。
6. 只接受 `Mode: 3`。
7. 解析 `[HitObjects]`，区分 tap / hold。
8. 解析 `[TimingPoints]`，分离红线 / 绿线。
9. 对 `4K.osz` 输出每个谱面的摘要：
   - title
   - version
   - key count
   - hit object count
   - timing point count
   - audio filename
   - background filename

### Phase 2：生成 USC

1. 建立 BPM segment 模型。
2. 实现 `time_ms_to_beat()`。
3. 按第一条红线作为 beat 0。
4. 生成 `bpm` objects。
5. 生成 `timeScaleGroup` object。
6. Tap 转 `single`。
7. Hold 转 `slide`。
8. 输出 `.usc.json`。
9. 用 `testdata/Next_Insane.usc` 对照 USC 大致格式。

### Phase 3：确认 offset

1. 制作或挑选一个很小的 4K mania 谱面。
2. 生成两版 USC：
   - `usc.offset = -first_red_time_ms / 1000`
   - `usc.offset = first_red_time_ms / 1000`
3. 分别转 LevelData 并打包。
4. 导入 Sonolus，确认哪一版音乐和音符对齐。
5. 把确认结果写进新项目 README。

### Phase 4：移植 NextRUSH+ uscToLevelData

1. 读取上游 `js/src/usc/index.ts` 和 `js/src/usc/convert.ts`。
2. 在 Python 中定义 USC dataclass 或直接处理 dict。
3. 实现 LevelData entity builder。
4. 实现 BPM / timeScaleGroup。
5. 实现 `single`。
6. 实现 `slide` start / connector / end。
7. 实现 SimLine 生成。
8. 暂不实现 osu!mania 不需要的 guide / damage / skill / fever。
9. 用简单 USC 样例做 JSON diff / 行为对照，确保字段名和 archetype 名贴近上游。

### Phase 5：打包 SCP

1. 读取 `engine.scp`。
2. 复制 NextRUSH+ engine、skin、effect、particle 相关 docs 和 repository blobs。
3. 生成 LevelData gzip blob。
4. 写入原始 BGM blob（不要 gzip）。
5. 将 cover/background image 转成 PNG 后写入 image blob。
6. 构造 `sonolus/levels/<level_name>`。
7. 构造 `sonolus/levels/list`。
8. 构造必要的 package / info docs。
9. 校验所有 `/sonolus/repository/<hash>` 是否存在。
10. 写出 `.scp`。

### Phase 6：多谱面和资源复用

1. 一个 `.osz` 内每个有效 `.osu` 生成一个 Sonolus level。
2. 同一个音频 / 图片只写入一次 repository。
3. 过滤明显占位谱面，例如 HitObject 数极少或 version 为 `delete this`。
4. 增加 `--single-difficulty` 只打包一个难度。
5. 增加 `--include-all` 强制包含所有 mania 谱面。

### Phase 7：验证

1. 用 `4K.osz` 生成 SCP。
2. 导入 Sonolus。
3. 检查：
   - 包能否导入。
   - level list 是否显示正常。
   - 音频是否播放。
   - cover 是否显示。
   - tap 轨道是否正确。
   - hold 起止时间是否正确。
   - BPM 变化是否正确。
   - SV 是否至少不造成明显错乱。
4. 记录已知问题和测试设备 / Sonolus 版本。

### Phase 8：后续增强

1. 更精确的 mania SV 映射。
2. 背景资源真正进入游玩背景，而不只是 cover。
3. hitsound 解析和可选保留。
4. 多 key 数支持，例如 5K、6K、7K（最终只需要实现4K、5K、6K、7K的转换支持）。
5. 更完整的 `.osu` 编码兼容。
6. 更严格的 SCP schema 校验。
7. 与上游 NextRUSH+ converter 更新保持同步。

## 已知风险

- `usc.offset` 符号必须实测。
- mania 轨道宽度到 NextRUSH+ `lane` / `size` 的映射以 `testdata/key4.usc`、`testdata/key5.usc`、`testdata/key6.usc` 为当前参考。
- osu!mania SV 与 NextRUSH+ `timeScale` 不一定完全等价。
- `.osu` hitsound / sampleSet 初期可能被忽略。
- `.osz` 内可能有非 mania 谱面、占位谱面或缺失资源。
- 游玩背景和 level cover 是两个问题。MVP 可以先只设置 cover。

## 最小可行交付标准

第一版脚本满足以下条件即可认为可用：

1. 能读取 `4K.osz`。
2. 能列出所有有效 mania 难度。
3. 能把至少一个难度转换成 USC。
4. 能把 USC 转成 NextRUSH+ LevelData。
5. 能使用 `engine.scp` 生成 `.scp`。
6. `.scp` 可以导入 Sonolus。
7. tap / hold 的轨道和时间大体正确。
8. README 明确记录 offset、SV、背景资源的当前处理方式。
