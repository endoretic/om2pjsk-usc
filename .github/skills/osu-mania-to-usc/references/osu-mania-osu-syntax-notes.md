# osu!mania `.osu` 语法速记（给 Codex/脚本开发用）

> 目标：把 osu!mania 的 `.osu` 里 **时间、轨道（列）、长按、BPM/SV、offset** 等关键信息讲清楚，方便你继续做解析/转换（例如转 Sonolus）。

---

## 1. 文件结构总览

`.osu` 文件按段落（section）组织，常见段包括：

- `[General]`：音频文件名、模式、AudioLeadIn 等
- `[Difficulty]`：HP/CS/OD/AR 等（mania 里 CS = key count）
- `[TimingPoints]`：红线/绿线（BPM、SV、sampleset、音量、Kiai 等）
- `[HitObjects]`：所有物件（mania 里主要是 **tap** 与 **hold**）

**mania 模式**通过 `[General]` 的 `Mode: 3` 标记。

---

## 2. `[Difficulty]`：key count（轨道数量）

- `CircleSize` 在 osu!mania 中 **表示 key count**（例如 `CircleSize:5` = 5K）。
- 实际写入 `.osu` 仍然是 `CircleSize:`，编辑器里 UI 可能显示为 “Key Count”。

> 实战建议：解析时 `keyCount = int(round(CircleSize))`，并对异常值做保护（<=0 则报错或默认 4K）。

---

## 3. `[HitObjects]`：物件如何写“时间 + 轨道”

### 3.1 通用行格式

每行一个物件：

```text
x,y,time,type,hitSound,objectParams,hitSample
```

- `time`：整数，单位 ms，从音频开头开始计时。
- `type`：位标志（bit flags）。mania 关键在：
  - bit0 = 1：hit circle（在 mania 中变成普通 note）
  - bit7 = 128：mania hold note（长按）
- `hitSample` 常见默认值 `0:0:0:0:`（不写也默认这个）

### 3.2 mania：`x` 如何决定第几轨（列）

mania 里 **不使用 `y` 来确定轨道**，主要看 `x`：

**列索引（0-based）**：
```text
col = clamp( floor(x * keyCount / 512), 0, keyCount-1 )
```

**轨道号（1-based，人更好读）**：
```text
lane = col + 1
```

> `x` 的范围通常 0–512（实际上是 osu!pixels 坐标系宽度）。边界上（例如 5K 时的 x=205/308 之类）会因为 `floor` 落到右侧/左侧某列，这就是常见“边界 note”现象。

### 3.3 普通 note（tap）

通常就是 `type = 1`（bit0 打开）。示例：

```text
153,192,1019,1,0,0:0:0:0:
```

含义（5K 时）：
- `time=1019ms`
- `x=153` → `lane = floor(153*5/512)+1 = 2` → 第2轨
- `y=192` 在 mania 里基本固定写这个（不决定轨道）
- `hitSound=0` 没额外 hitsound

### 3.4 长按（hold, mania only）

**hold 行格式**（注意参数不再是 `objectParams,hitSample`，而是把 endTime 放在前面）：

```text
x,y,time,type,hitSound,endTime:hitSample
```

- `time`：长按开始时间（ms）
- `endTime`：长按结束时间（ms）
- 持续时长：`duration = endTime - time`
- `x`：同样决定轨道；`y` 对 hold 也不影响，默认 192

示例：

```text
358,192,1756,128,0,1966:0:0:0:0:
```

含义（5K 时）：
- 第4轨（`floor(358*5/512)+1 = 4`）
- 开始 1756ms，结束 1966ms，持续 210ms

---

## 4. 你那段 `[HitObjects]`（CircleSize:5）逐行解析示例

给定 `keyCount = 5`：

| 行 | x | time(ms) | type | lane(1-based) | 说明 |
|---:|---:|---:|---:|---:|---|
| 1 | 51  | 914  | 1   | 1 | tap |
| 2 | 153 | 1019 | 1   | 2 | tap |
| 3 | 256 | 1124 | 1   | 3 | tap |
| 4 | 153 | 1335 | 1   | 2 | tap |
| 5 | 256 | 1440 | 1   | 3 | tap |
| 6 | 153 | 1545 | 1   | 2 | tap |
| 7 | 256 | 1650 | 1   | 3 | tap |
| 8 | 358 | 1756 | 128 | 4 | hold，endTime=1966（210ms） |

lane 计算公式：`lane = floor(x * 5 / 512) + 1`

---

## 5. `[TimingPoints]`：红线/绿线行格式与含义

### 5.1 行格式

```text
time,beatLength,meter,sampleSet,sampleIndex,volume,uninherited,effects
```

- `time`：该 timing section 起点（ms），允许小数（Decimal）
- `beatLength`：
  - **红线（uninherited=1）**：每拍时长（ms/beat）
  - **绿线（uninherited=0）**：负数，表示 “负的反向 SV 倍率百分比”
- `meter`：每小节拍数（红线有效，绿线忽略）
- `sampleSet`：0=谱面默认，1=normal，2=soft，3=drum
- `sampleIndex`：自定义采样编号，0=默认
- `volume`：音量百分比（0–100）
- `uninherited`：1=红线（BPM/拍号），0=绿线（SV/音量/采样/Kiai）
- `effects`：位标志（常见：bit0=Kiai；bit3=taiko/mania 省略第一条小节线）

### 5.2 由 `beatLength` 计算 BPM（红线）

若 `uninherited=1`：
```text
BPM = 60000 / beatLength
```

你给的例子：

```text
2598.14313743447,421.023086099221,4,1,0,100,1,0
```

- 红线起点：2598.143ms
- `beatLength = 421.023... ms/beat`
- `BPM ≈ 60000 / 421.023... = 142.51 BPM`
- 拍号：4（常见 4/4）
- sampleset normal，sampleIndex=0，volume=100%，无 Kiai/省略小节线

### 5.3 由 `beatLength` 计算 SV 倍率（绿线）

若 `uninherited=0`（通常 `beatLength` 为负数）：

wiki 的例子：`-25` 代表 4x（因为 `100/25 = 4`），`-50` 代表 2x。

因此可用：
```text
svMultiplier = 100 / abs(beatLength)
```

> mania 里虽然没有 slider，但这套 “SV/滚速变化”仍用于控制谱面的滚动速度变化（常见“变速”）。

---

## 6. 音乐与谱面“offset”在文件里怎么体现？

### 6.1 Mapping 意义上的 “beatmap offset”（第一拍偏移）

- “beatmap offset”通常指：**音频开始到第一拍（first downbeat）的时间差**  
- 在文件层面，它由 timing points 控制：你通常会看到第一条红线（uninherited timing point）的 `time` 就落在“第一拍”对应位置。

### 6.2 `[General] AudioLeadIn`（不是红线 offset，但会影响开头体验）

- `AudioLeadIn: N` 表示：音频播放前的 **额外静音毫秒**。更像“开局缓冲”，并不是 BPM 对齐用的红线 offset。

### 6.3 玩家侧 offset（不写进谱面逻辑里）

- **Local offset**：单张图的玩家校准；移动 gameplay 元素相对音频
- **Universal offset**：全局校准；它是“移动音频相对 gameplay”，方向与 local 相反

> 做转换工具时，一般只处理 `.osu` 文件内的 timing/hitobject 时间；玩家侧 offset 属于运行时设置，不应该写入转换结果（除非你明确想 bake-in）。

---

## 7. 解析/转换实现提示（给 Codex）

### 7.1 解析流程（推荐）

1. 逐行读文件，识别 section（`[General]` / `[Difficulty]` / ...）
2. `[General]`：
   - `Mode` 必须是 3 才按 mania 规则解析
   - 记录 `AudioLeadIn`（可选）
3. `[Difficulty]`：
   - `keyCount = int(CircleSize)`
4. `[TimingPoints]`：
   - 解析成 list（按 `time` 升序）
   - 对每条记录计算：
     - `isRed = (uninherited == 1)`
     - red：`bpm = 60000/beatLength`
     - green：`sv = 100/abs(beatLength)`
5. `[HitObjects]`：
   - 解析 `x,y,time,type,hitSound,...`
   - 判断 `isHold = (type & 128) != 0`
   - 轨道：`lane = clamp(floor(x*keyCount/512),0,keyCount-1) + 1`
   - tap：`start=time`
   - hold：从 params 中取 `endTime`（逗号后第一个字段里以 `:` 分割）

### 7.2 常见坑

- TimingPoints 的 `time` 是 Decimal（可能有小数）；HitObjects 的 `time` 是 Integer
- 某些谱面会把 timing point 时间写得非常精细（浮点误差/不同客户端处理差异），解析时建议用 `float`，内部计算再做合理四舍五入/容差
- `x` 恰好落在分段边界时（如 5K 的 102/103、204/205…），`floor` 的方向会导致“落左列/右列”，转换时要严格按公式，别用 `round`
- mania 不用 slider/spinner；如果遇到 `type` 同时包含其它位，建议：
  - 先识别是否 hold（bit7）
  - 否则当作 tap（bit0）
  - 对未知组合做日志/告警

---

## 8. 参考来源（建议你在 Codex 里一起打开）

- osu! wiki：`.osu (file format)`  
  https://osu.ppy.sh/wiki/en/Client/File_formats/osu_%28file_format%29
- osu! wiki：Circle size（mania：CS=key count）  
  https://osu.ppy.sh/wiki/en/Beatmap/Circle_size
- osu! wiki：Offset（offset 类型：red line / green line / beatmap offset / local / universal）  
  https://osu.ppy.sh/wiki/en/Offset  
  https://osu.ppy.sh/wiki/en/Offset/Local_offset  
  https://osu.ppy.sh/wiki/en/Offset/Universal_offset

---

如果你下一步是“转 Sonolus”，建议你先明确：目标引擎吃的 chart 格式（是否真的用 `.usc`，还是引擎自定义 json / binary），然后再把上面解析出来的 `(lane, time, endTime?, bpm, sv)` 映射成目标事件模型。
