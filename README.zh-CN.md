# codex-usage

[English](README.md) · **中文**

本地 Codex 用量统计：解析 `~/.codex/sessions` 的 rollout 会话文件，按 **会话 / 子代理 / 天 / 模型** 任意聚合，用终端表格（[rich](https://github.com/Textualize/rich)）或图表展示，并按模型折算成本。

图表默认出**真图**：[matplotlib](https://matplotlib.org/) 渲染 PNG 后由 [textual-image](https://github.com/lnqs/textual-image) 送进终端——支持图形协议（kitty / Sixel）的终端直接显示图片，其余终端显示彩色半块字符；装了可选依赖且输出是终端时才会启用。未装依赖、输出被管道重定向或加 `--ascii` 时，回退到字符画（[plotext](https://github.com/piccolomo/plotext) + [termcharts](https://github.com/zvovcahovo/termcharts)）。

全程本地运行、只读本地文件；唯一的联网动作是显式的 `codex-usage --update-pricing` 刷新定价缓存，统计与出图不会联网。成本按定价表折算，取值顺序为 `CODEX_USAGE_PRICING_FILE` → 本地缓存 → 内置公开定价表（详见 [docs/pricing.md](docs/pricing.md)）。无定价的模型 token 照常统计，成本按 $0 计，行内标 `*`。

## 为什么是它

五条能指到证据的差异；完整对照、劣势清单与全部引用见 [docs/competitors.md](docs/competitors.md)。

- **终端里的真图**：matplotlib 出 PNG 由 textual-image 送进终端——支持图形协议（kitty TGP / Sixel）的终端显示真图，其余显示彩色半块，未装 extras / 被管道重定向 / `--ascii` 时退到字符画，`CODEX_USAGE_IMAGE_MODE` 可强制档位。本次调研的 11 个项目里，图表基本都在 Web / 桌面 dashboard，只有 anthropometer 出 PDF，没有一家在 README 里写明支持终端图形协议。
- **机器可读的自描述**：`--schema` 的选项清单由 argparse 定义生成（不会与实现漂移），并给出 `--json` 字段契约与图表档位的环境变量；`--doctor` 自检数据源、定价层、真图依赖、终端档位与中文字体，支持 `--json` 供 Agent 消费。
- **子代理与家族树是一等公民**：逐文件解析、子代理按昵称+角色单列，`--family` 把主线程与各子代理放进同一棵树；部分聚合工具从更高层状态派生 Codex 用量，fork 之后可能永久延迟会话（[farion1231/cc-switch#5687](https://github.com/farion1231/cc-switch/issues/5687)）。
- **默认离线**：统计、聚合、出图全程不联网，内置定价快照（2086 个模型）让装完就有可用的成本列；`--update-pricing` 是唯一联网动作，且只在显式触发时发生。
- **口径与测试可验证**：按每轮 `last_token_usage` 增量累加，而不是被上下文压缩重置的 `total_token_usage` 累计值（实测有会话末值仅为真实消耗的 1/9）。增量口径并非我们独有（业界正确做法），差异在逐文件解析、子代理单列、把四种聚合的合计钉住的不变量测试，以及 129 个跑在合成夹具上（不依赖本机 Codex 数据）、覆盖 Python 3.10–3.13 CI 矩阵的用例。

如实说明差距：[ccusage](https://github.com/ccusage/ccusage) 有 18,520 stars（抓取日 2026-09-13）、覆盖 18 个 CLI、`npx` 一行即用；codex-usage 是单数据源、单作者的项目。我们想做的是**把 Codex 一件事做深**，而不是再做一个横跨 40 个工具的聚合面板。

## 安装

要求 **Python ≥ 3.10**。

```bash
uv tool install codex-usage                                          # 基础：表格 + 字符画图表
uv tool install "git+https://github.com/stofancy/codex-usage[image]" # 可选：加终端真图图表
```

可选 extras `[image]` 会装上 matplotlib 与 textual-image，其中 `textual-image` 要求 **Python ≥ 3.12**；Python 3.10/3.11 下图表保持字符画，其余功能不受影响。未装 extras、输出不是终端或加 `--ascii` 时，图表自动回退字符画。

## 使用

```bash
codex-usage                                          # 今天的会话明细（含子代理，每会话一行）
codex-usage --by-model                               # 按模型聚合（每模型一行，含会话数）
codex-usage --by-day --since 2026-09-04              # 按天聚合
codex-usage --by-day --by-model --since 2026-09-04   # 天×模型
codex-usage --family --parent 01a083b7 --since 2026-09-09     # 家族树：主线程+各子代理
codex-usage --family --by-model --since 2026-09-09            # 家族×模型
codex-usage --raw --type subagent                    # 文件粒度：每个子代理文件一行
codex-usage --since "2026-09-11 09:00" --until "2026-09-11 14:00"   # 分钟级时间过滤
codex-usage --by-model --since 20260912-161023       # 紧凑时间：同 2026-09-12 16:10:23
codex-usage --by-model --since 20260912-16           # 紧凑时间：同 2026-09-12 16:00
codex-usage --chart pie                              # 饼图：各模型成本分布
codex-usage --chart bar --by-day --by-model --metric total   # 堆叠柱状图
codex-usage --chart area --by-day --metric cache     # 面积图：每天缓存读趋势
codex-usage --chart bar --by-day --ascii             # 强制字符画（默认终端下优先真图）
codex-usage --json                                   # 机器可读输出（含按模型明细）
codex-usage --help                                   # 自说明帮助（/? 、-? 、help 等价）
codex-usage --schema                                 # 机器可读自描述（JSON 契约）
codex-usage --doctor                                 # 环境自检（数据源/定价/真图能力）
codex-usage --update-pricing                         # 刷新本地定价缓存（唯一联网动作）
```

### 时间格式

`--since` / `--until` 支持两种写法，可混用：

| 写法 | 示例 | 含义 |
|---|---|---|
| 显式 | `2026-09-12`、`2026-09-12 16:10`、`2026-09-12T16:10:23` | 常规格式 |
| 紧凑 | `20260912`、`20260912-16`、`20260912-1610`、`20260912-161023` | `YYYYMMDD[-时[分[秒]]]`，分隔符也可用空格 `.` `T`，时间可写 `16:10:23` |

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
| 输出 | `--json` | 会话级 JSON Lines，含按模型明细（含调用次数），与其他参数兼容 |
| 自述 | `--schema` `--doctor` | 机器可读契约 / 环境自检，优先于其它参数 |

无定价模型：token 照常统计，成本按 $0 计，行内标 `*`，表尾列出模型名。

## 定价

token 统计完全在本地完成，只有成本列需要价格。`codex-usage` 随包内置一份**公开定价快照**（来源 `models.dev`，当前 2086 个有价模型），因此装完即可离线算成本。三层按 `modelId` **合并**，高优先级层的同名条目覆盖低优先级层：

| 优先级 | 来源 | 作用 |
|---|---|---|
| 低 | 内置表 `src/codex_usage/data/pricing.json` | 公开模型的基础覆盖 |
| 中 | 用户缓存 `~/.cache/codex-usage/pricing.json`（目录可用 `CODEX_USAGE_CACHE_DIR` 覆盖） | `--update-pricing` 写入 |
| 高 | `CODEX_USAGE_PRICING_FILE`（未设置时为 `~/.cc-switch/model-pricing.json`） | 你自己的私有定价 |

任一层缺失 / 为空 / JSON 损坏只跳过该层；三层都不可用时 token 照常统计、成本显示 `$0.00*`。文件格式与 cc-switch 兼容 —— `{"models":[{"modelId": …, "inputCostPerMillion": …, "cacheReadCostPerMillion": …, "outputCostPerMillion": …}]}` —— 已有 cc-switch 表可继续使用，只覆盖它定义的同名条目。

从公开渠道刷新缓存（全局唯一的联网动作，且只在显式触发时发生）：

```bash
codex-usage --update-pricing                         # 默认 models.dev
codex-usage --update-pricing --pricing-source litellm
```

会话里的模型名按「精确 → 归一化（大小写、provider 前缀、日期与 `-latest` 后缀、常见别名）→ 最长前缀」三档匹配，因此 `gpt-5.1-codex-2025-11-13`、`openrouter/openai/GPT-5.1-Codex` 都能落到 `gpt-5.1-codex`。

注意：内置表是快照（文件里有 `updated` 时间戳）；context 阶梯价（`>200k`）、缓存写价与转售商加价不建模；公开渠道查不到价格的模型保持 `$0.00*`。需要精确账单请把自建表放到 `CODEX_USAGE_PRICING_FILE`。数据源、字段映射与许可见 [docs/pricing.md](docs/pricing.md)。

## 自描述与自检（给人，也给 Agent）

工具不需要外部文档就能说清自己怎么用、能输出什么、当前环境是否正常。

`codex-usage --help`（`/?`、`-?`、`help` 等价）结尾是一份结构化说明：先列帮助入口，再分四段——示例命令、语义约定、输出与退出码、数据源与环境变量。`codex-usage --schema` 是同一份契约的 JSON 版——选项清单直接由 argparse 定义生成，不会和实现漂移：

```bash
codex-usage --schema | jq '.options[] | select(.flags | index("--chart"))'
codex-usage --schema | jq '.json_output.fields'   # --json 每行记录的字段含义与单位
codex-usage --json --since 20260910 | jq -c '{id:.session_id,total:.total_tokens,calls}' | head -3
```

`codex-usage --doctor`（加 `--json` 得到结构化结果）做环境自检：会话与归档目录是否存在、有多少 rollout 文件、当前生效的定价来源与模型数、真图依赖与终端档位、中文字体；有可操作建议时单独列出，`ok` 字段表示是否一切正常。

![codex-usage --doctor](docs/shots/doctor.png)

```text
$ codex-usage --doctor
codex-usage 0.1.0  |  Python 3.14.7  |  Linux-...

会话数据   /tmp/codex-usage-doc-fixture/sessions  存在，32 个 rollout 文件（最近 2026-09-13 23:36）
归档数据   /tmp/codex-usage-doc-fixture/archived_sessions  存在，0 个 rollout 文件
定价       内置表+自定义文件 /tmp/codex-usage-doc-fixture/model-pricing.json，2086 个模型（数据 2026-09-13）
图表渲染   彩色半块（matplotlib 3.11.2 + textual-image 0.13.2，光栅 119×84，档位 auto（探测为 彩色半块））
中文字体   Noto Sans CJK SC

结论: 一切正常
```

约定：数据只写到 stdout，提示与错误只写到 stderr（因此 `codex-usage --json … | jq` 不会被噪声打断）；退出码 `0` 成功、`1` 用法或运行时错误、`2` 参数解析错误、`141` 管道下游提前关闭。

## 图表

`--chart` 的数据来自聚合维度：饼图按模型，柱状按天/模型/天×模型（天×模型自动堆叠），面积与折线按天趋势（配 `--by-model` 出多序列+图例）。`--chart` 不与 `--family` 组合，`--chart pie` 不与 `--by-day` 组合（饼图只按模型）；`--json` 优先于 `--chart`。

渲染分三档，按运行环境自动选择：

| 环境 | 渲染 |
|---|---|
| 终端支持图形协议（kitty / Ghostty / WezTerm / Konsole / foot / xterm-sixel 等），且装了 `[image]` | matplotlib 出 PNG，终端直接显示真图（中文标签正常） |
| 终端不支持图形协议，但装了 `[image]` | 同一张 PNG 转成彩色半块字符（形状与颜色可辨，文字较粗） |
| 未装 `[image]`、输出被管道/重定向、或指定 `--ascii` | plotext / termcharts 字符画 |

出图分辨率按终端能显示的光栅尺寸定（避免把 PNG 缩放十几倍后细线被抹平），x 轴标签过多自动抽稀，轴刻度用 `120K` / `3.4B` 这类短写法。

三档的实际观感（同一窗口 `--since 2026-09-04 --until 2026-09-13 --chart bar --by-day`）：

| 档位 | 效果 |
|---|---|
| 真图（kitty TGP / Sixel） | ![kitty 真图](docs/shots/chart-bar-kitty.png) |
| 彩色半块（不支持图形协议的终端） | ![半块](docs/shots/chart-bar-halfcell.png) |
| 字符画（`--ascii`、未装 `[image]`、或输出被重定向） | ![字符画](docs/shots/chart-bar-ascii.png) |

真图是 matplotlib 的原图，文字清晰；半块用两个像素挤进一个字符格，形状与配色可辨但文字偏毛糙；字符画最小、兼容性最好。字符画档位下标题与图例会自动转写成 ASCII（plotext 按 1 列 = 1 字符排版，中文这类宽字符会错位成乱码），真图与半块档位仍用中文。

### 强制指定档位

自动探测偶尔会失灵（例如某些终端声称支持图形协议但渲染异常），可以用环境变量覆盖：

```bash
CODEX_USAGE_IMAGE_MODE=halfcell codex-usage --chart bar --by-model   # 降级到彩色半块
CODEX_USAGE_IMAGE_MODE=tgp      codex-usage --chart bar --by-model   # 强制 kitty 图形协议
CODEX_USAGE_IMAGE_MODE=ascii    codex-usage --chart bar --by-model   # 等同 --ascii
```

取值 `auto`（默认，自动探测）｜`tgp`｜`sixel`｜`halfcell`｜`ascii`；非法值按 `auto` 处理。当前生效档位、自动探测结果都会由 `codex-usage --doctor` 报出，Agent 也可以从 `codex-usage --schema` 的 `chart_rendering.env` 里读到。

其它视图的示例（按模型成本表格、天×模型堆叠柱、成本占比饼图、每天成本面积图）：

| 表格（按模型） | 堆叠柱（天×模型） |
|---|---|
| ![table](docs/shots/table-bymodel.png) | ![stacked](docs/shots/chart-bar-stacked-kitty.png) |

| 饼图（真图） | 面积图（真图） |
|---|---|
| ![pie](docs/shots/chart-pie-kitty.png) | ![area](docs/shots/chart-area-kitty.png) |

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

数据路径可用环境变量覆盖：`CODEX_USAGE_SESSIONS_DIR`、`CODEX_USAGE_ARCHIVE_DIR`、`CODEX_USAGE_PRICING_FILE`、`CODEX_USAGE_CACHE_DIR`。

`docs/shots/` 下的示例图由 [`tools/make_doc_shots.py`](tools/make_doc_shots.py) 用合成夹具（公开模型名 + 公开定价）生成，不含任何真实会话数据：

```bash
.venv/bin/python tools/make_doc_shots.py --clean
```

参与贡献见 [CONTRIBUTING.md](CONTRIBUTING.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。

## 已知边界

- 只解析 OpenAI 官方订阅（OAuth）产生的 rollout 文件；第三方网关的用量不在本地会话文件里。
- 时间过滤按事件时间戳（UTC→本地时区）判定，跨窗口会话只统计窗口内的轮次；按天分组按会话活动起点。
- 与 ccusage 等工具按天对账可能有出入：本工具按会话活动起点归日、按增量计量，全局总量口径一致。
- 真图图表依赖 textual-image 探测终端图形协议：tmux 需开启 passthrough，个别终端拿不到格子像素时按默认值出图，显示尺寸可能与终端略有出入；不想要真图用 `--ascii`。
- 面向人的可读输出目前只有中文；JSON 契约与字段不依赖语言。

## License

[MIT](LICENSE)
