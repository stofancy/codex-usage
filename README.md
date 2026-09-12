# codex-usage

本地 Codex 用量统计：解析 `~/.codex/sessions` 的 rollout 会话文件，按 **会话 / 子代理 / 天 / 模型** 任意聚合，终端表格（[rich](https://github.com/Textualize/rich)）与图表（[plotext](https://github.com/piccolomo/plotext) + [termcharts](https://github.com/zvovcahovo/termcharts)）展示，并按模型折算成本。

纯本地运行，不联网；成本折算复用 [cc-switch](https://github.com/farion1231/cc-switch) 维护的定价表（无该文件时 token 照常统计、成本按 $0 计）。

## 为什么是它

- **子代理可见**：cc-switch 等工具会把部分子代理会话永久漏统计（[farion1231/cc-switch#5687](https://github.com/farion1231/cc-switch/issues/5687)），本工具逐文件解析、子代理按昵称+角色单列。
- **计量更真实**：按每轮 `last_token_usage` 增量累加，而不是被上下文压缩重置污染的 `total_token_usage` 累计值（实测有会话末值仅为真实消耗的 1/9）。
- **聚合自由组合**：`--by-*` 是聚合维度、`--xx 值` 是过滤器，逻辑通顺即可组合。

## 安装

```bash
uv tool install ~/workspaces/codex-usage   # 或 pipx install / pip install
```

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
codex-usage --chart pie                              # 饼图：各模型成本分布
codex-usage --chart bar --by-day --by-model --metric total        # 堆叠柱状图
codex-usage --chart area --by-day --metric cache     # 面积图：每天缓存读趋势
codex-usage --json                                   # 机器可读输出（含按模型明细）
```

### 语义约定

| 类别 | 参数 | 说明 |
|---|---|---|
| 聚合 | `--by-day` `--by-model` | 决定行粒度；可组合成 天×模型 |
| 结构 | `--family` `--raw` | 家族树 / 文件粒度实体 |
| 过滤 | `--since` `--until` `--type` `--model` `--session` `--parent` `--archived` | 只缩小范围，不改变行粒度 |
| 图表 | `--chart pie\|bar\|area\|line` `--metric cost\|input\|cache\|output\|total` | 数据来自聚合维度 |
| 输出 | `--json` | 会话级 JSON，含按模型明细，与其他参数兼容 |

无定价模型：token 照常统计，成本按 $0 计，行内标 `*`、表尾列出模型名。

## 图表

| 图型 | 数据 | 说明 |
|---|---|---|
| `pie` | 按模型 | 各模型占比（默认成本，可换指标） |
| `bar` | 天/模型/天×模型 | 天×模型自动堆叠 |
| `area` / `line` | 按天趋势 | 配合 `--by-model` 出多序列+图例 |

## 开发

```bash
uv venv && uv pip install -e . pytest
.venv/bin/python -m pytest tests/ -q     # 单元 + CLI 端到端（合成夹具，不依赖本机数据）
```

数据路径可用环境变量覆盖：`CODEX_USAGE_SESSIONS_DIR`、`CODEX_USAGE_ARCHIVE_DIR`、`CODEX_USAGE_PRICING_FILE`。

## 已知边界

- 只解析 OpenAI 官方订阅（OAuth）产生的 rollout 文件；第三方网关的用量不在本地会话文件里。
- 时间过滤按事件时间戳（UTC→本地时区）判定，跨窗口会话只统计窗口内的轮次；按天分组按会话活动起点。
- 与 ccusage 等工具按天对账可能有出入：本工具按会话活动起点归日、按增量计量，全局总量口径一致。

## License

MIT
