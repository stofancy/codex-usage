# codex-usage

本地 Codex 用量统计：解析 `~/.codex/sessions` 的 rollout 会话文件，按 **会话 / 子代理 / 天 / 模型** 任意聚合，终端表格（[rich](https://github.com/Textualize/rich)）与图表展示，并按模型折算成本。

图表默认出**真图**：[matplotlib](https://matplotlib.org/) 渲染 PNG 后由 [textual-image](https://github.com/lnqs/textual-image) 送进终端——支持图形协议（kitty / Sixel）的终端直接显示图片，其余终端显示彩色半块字符；装了可选依赖且输出是终端时才会启用。未装依赖、输出被管道重定向或加 `--ascii` 时，回退到字符画（[plotext](https://github.com/piccolomo/plotext) + [termcharts](https://github.com/zvovcahovo/termcharts)）。

纯本地运行，不联网；成本折算复用 [cc-switch](https://github.com/farion1231/cc-switch) 维护的定价表（无该文件时 token 照常统计、成本按 $0 计）。

## 为什么是它

- **子代理可见**：cc-switch 等工具会把部分子代理会话永久漏统计（[farion1231/cc-switch#5687](https://github.com/farion1231/cc-switch/issues/5687)），本工具逐文件解析、子代理按昵称+角色单列。
- **计量更真实**：按每轮 `last_token_usage` 增量累加，而不是被上下文压缩重置污染的 `total_token_usage` 累计值（实测有会话末值仅为真实消耗的 1/9）。
- **聚合自由组合**：`--by-*` 是聚合维度、`--xx 值` 是过滤器，逻辑通顺即可组合。

## 安装

```bash
uv tool install ~/workspaces/codex-usage              # 基础：表格 + 字符画图表
uv tool install "$HOME/workspaces/codex-usage[image]" # 可选：加终端真图图表（matplotlib + textual-image）
```

真图渲染是可选依赖，`textual-image` 要求 Python ≥3.12；未装或版本不够时图表自动回退字符画，其余功能不受影响。

## 使用

```fish
codex-usage                                          # 今天的会话明细（含子代理，每会话一行）
codex-usage --by-model                               # 按模型聚合（每模型一行，含会话数）
codex-usage --by-day --since 2026-09-04              # 按天聚合
codex-usage --by-day --by-model --since 2026-09-04   # 天×模型
codex-usage --family --parent 01a083b7 --since 2026-09-09        # 家族树：主线程+各子代理
codex-usage --family --by-model --since 2026-09-09               # 家族×模型聚合
codex-usage --raw --type subagent                    # 文件粒度看子代理
codex-usage --since "2026-09-11 09:00" --until "2026-09-11 14:00" # 分钟级时间过滤
codex-usage --by-model --since 20260912-161023       # 紧凑时间：同 2026-09-12 16:10:23
codex-usage --by-model --since 20260912-16           # 紧凑时间：同 2026-09-12 16:00
codex-usage --chart pie                              # 饼图：各模型成本分布
codex-usage --chart bar --by-day --by-model --metric total        # 堆叠柱状图
codex-usage --chart area --by-day --metric cache     # 面积图：每天缓存读趋势
codex-usage --chart bar --by-day --ascii             # 强制字符画（默认终端下优先真图）
codex-usage --json                                   # 机器可读输出（含按模型明细）
codex-usage --help                                   # 自说明帮助（/? 、-? 、help 等价）
codex-usage --schema                                 # 机器可读自描述（JSON 契约）
codex-usage --doctor                                 # 环境自检（数据源/定价/真图能力）
```

### 时间格式

`--since` / `--until` 支持两种写法，可混用：

| 写法 | 示例 | 含义 |
|---|---|---|
| 显式 | `2026-09-12`、`2026-09-12 16:10`、`2026-09-12T16:10:23` | 常规格式 |
| 紧凑 | `20260912`、`20260912-16`、`20260912-1610`、`20260912-161023` | `日期-时[分[秒]]`，分隔符也可用空格 `.` `T`，时间可写 `16:10:23` |

缺省部分 `--since` 补 0（如 `20260912-16` → 16:00:00）、`--until` 补满（→ 16:59:59，纯日期 → 23:59:59）。

### 表格列

| 列 | 口径 |
|---|---|
| 净输入 / 缓存读 / 输出 | token 数；净输入 = 毛输入 − 缓存读 |
| 总 tokens | 净输入 + 缓存读 + 输出 |
| 调用 | API 调用次数（`token_count` 轮次，按当时模型归因） |
| 单次成本 | 成本 ÷ 调用次数；无调用显示 `-` |
| 成本 | 按定价表折算；无定价模型计 $0 并标 `*` |

### 语义约定

| 类别 | 参数 | 说明 |
|---|---|---|
| 聚合 | `--by-day` `--by-model` | 决定行粒度；可组合成 天×模型 |
| 结构 | `--family` `--raw` | 家族树 / 文件粒度实体 |
| 过滤 | `--since` `--until` `--type` `--model` `--session` `--parent` `--archived` | 只缩小范围，不改变行粒度 |
| 图表 | `--chart pie\|bar\|area\|line` `--metric cost\|input\|cache\|output\|total` `--ascii` | 数据来自聚合维度，`--ascii` 强制字符画 |
| 输出 | `--json` | 会话级 JSON，含按模型明细（含调用次数），与其他参数兼容 |
| 自述 | `--schema` `--doctor` | 机器可读契约 / 环境自检，优先于其它参数 |

无定价模型：token 照常统计，成本按 $0 计，行内标 `*`、表尾列出模型名。

## 自描述与自检（给人，也给 Agent）

工具不需要外部文档就能说清自己怎么用、能输出什么、当前环境是否正常。

`codex-usage --help`（`/?`、`-?`、`help` 等价）分成四段：示例命令、语义约定、输出与退出码、数据源与环境变量。`codex-usage --schema` 是同一份契约的 JSON 版——选项清单直接由 argparse 定义生成，不会和实现漂移：

```fish
codex-usage --schema | jq '.options[] | select(.flags | index("--chart"))'
codex-usage --schema | jq '.json_output.fields'        # --json 每行记录的字段含义与单位
codex-usage --json --since 20260910 | jq -c '{id:.session_id,total:.total_tokens,calls}' | head -3
```

`codex-usage --doctor`（加 `--json` 得到结构化结果）做环境自检：会话与归档目录是否存在、有多少 rollout 文件、定价表加载了多少模型、真图依赖与终端档位、中文字体；有可操作建议时单独列出，`ok` 字段表示是否一切正常。

```text
$ codex-usage --doctor
codex-usage 1.0.0  |  Python 3.12.13  |  Linux-...
会话数据   ~/.codex/sessions  存在，1348 个 rollout 文件（最近 2026-09-12 23:36）
定价表     ~/.cc-switch/model-pricing.json  存在，56 个模型
图表渲染   真图（kitty 图形协议）（matplotlib 3.11.2 + textual-image 0.13.2，光栅 1190×760）
中文字体   Noto Sans CJK SC
结论: 一切正常
```

约定：数据只写到 stdout，提示与错误只写到 stderr（因此 `codex-usage --json … | jq` 不会被噪声打断）；退出码 `0` 成功、`1` 用法或运行时错误、`2` 参数解析错误、`141` 管道下游提前关闭。

## 图表

`--chart` 的数据来自聚合维度：饼图按模型，柱状按天/模型/天×模型（天×模型自动堆叠），面积与折线按天趋势（配 `--by-model` 出多序列+图例）。

渲染分三档，按运行环境自动选择：

| 环境 | 渲染 |
|---|---|
| 终端支持图形协议（kitty / Ghostty / WezTerm / Konsole / foot / xterm-sixel 等），且装了 `[image]` | matplotlib 出 PNG，终端直接显示真图（中文标签正常） |
| 终端不支持图形协议，但装了 `[image]` | 同一张 PNG 转成彩色半块字符（形状与颜色可辨，文字较粗） |
| 未装 `[image]`、输出被管道/重定向、或指定 `--ascii` | plotext / termcharts 字符画 |

出图分辨率按终端能显示的光栅尺寸定（避免把 PNG 缩放十几倍后细线被抹平），x 轴标签过多自动抽稀，轴刻度用 `120K` / `3.4B` 这类短写法。

三档的实际观感（同一窗口 `--since "2026-09-12 14:10" --chart bar --by-model`）：

| 档位 | 效果 |
|---|---|
| 真图（kitty TGP / Sixel） | ![kitty 真图](docs/shots/chart-bar-kitty.png) |
| 彩色半块（不支持图形协议的终端） | ![半块](docs/shots/chart-bar-halfcell.png) |
| 字符画（`--ascii`、未装 `[image]`、或输出被重定向） | ![字符画](docs/shots/chart-bar-ascii.png) |

真图是 matplotlib 的原图，文字清晰；半块用两个像素挤进一个字符格，形状与配色可辨但文字偏毛糙；字符画最小、兼容性最好。字符画档位下标题与图例会自动转写成 ASCII（plotext 按 1 列 = 1 字符排版，中文这类宽字符会错位成乱码），真图与半块档位仍用中文。

### 强制指定档位

自动探测偶尔会失灵（例如某些终端声称支持图形协议但渲染异常），可以用环境变量覆盖：

```fish
CODEX_USAGE_IMAGE_MODE=halfcell codex-usage --chart bar --by-model   # 降级到彩色半块
CODEX_USAGE_IMAGE_MODE=tgp      codex-usage --chart bar --by-model   # 强制 kitty 图形协议
CODEX_USAGE_IMAGE_MODE=ascii    codex-usage --chart bar --by-model   # 等同 --ascii
```

取值 `auto`（默认，自动探测）｜`tgp`｜`sixel`｜`halfcell`｜`ascii`；非法值按 `auto` 处理。当前生效档位、自动探测结果都会由 `codex-usage --doctor` 报出，Agent 也可以从 `codex-usage --schema` 的 `chart_rendering.env` 里读到。

其它视图的示例（按模型成本表格、成本占比饼图、每天成本面积图）：

| 表格 | 饼图（真图） | 面积图（真图） |
|---|---|---|
| ![table](docs/shots/table-bymodel.png) | ![pie](docs/shots/chart-pie-kitty.png) | ![area](docs/shots/chart-area-kitty.png) |

| 图型 | 数据 | 说明 |
|---|---|---|
| `pie` | 按模型 | 各模型占比（默认成本，可换指标） |
| `bar` | 天/模型/天×模型 | 天×模型自动堆叠 |
| `area` / `line` | 按天趋势 | 配合 `--by-model` 出多序列+图例 |

## 开发

```bash
uv venv && uv pip install -e ".[image]" pytest   # 含真图依赖；只装 -e . pytest 时真图用例自动跳过
.venv/bin/python -m pytest tests/ -q             # 单元 + CLI 端到端（合成夹具，不依赖本机数据）
```

数据路径可用环境变量覆盖：`CODEX_USAGE_SESSIONS_DIR`、`CODEX_USAGE_ARCHIVE_DIR`、`CODEX_USAGE_PRICING_FILE`。

## 已知边界

- 只解析 OpenAI 官方订阅（OAuth）产生的 rollout 文件；第三方网关的用量不在本地会话文件里。
- 时间过滤按事件时间戳（UTC→本地时区）判定，跨窗口会话只统计窗口内的轮次；按天分组按会话活动起点。
- 与 ccusage 等工具按天对账可能有出入：本工具按会话活动起点归日、按增量计量，全局总量口径一致。
- 真图图表依赖 textual-image 探测终端图形协议：tmux 需开启 passthrough，个别终端拿不到格子像素时按默认值出图，显示尺寸可能与终端略有出入；不想要真图用 `--ascii`。

## License

MIT
