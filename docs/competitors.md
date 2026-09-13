# codex-usage 竞品调研（开源前市场/定位分析）

> 任务：T5 竞品调研：能力对照、优势素材、劣势清单
> 调研负责人：research-dev ｜ 抓取日期：**2026-09-13（UTC）**
> 本文所有外部数据均来自当日直连抓取（GitHub REST API + 各仓库 README 原文 + npm registry），不依赖搜索结果摘要。
> 涉及的仓库当前状态可能已变化；引用时请连同抓取日期一起引用。

## 0. 方法与标注约定

**抓取方式（可复现）**

```bash
curl -s https://api.github.com/repos/<owner>/<repo>                              # star/fork/pushed_at/license/language
curl -sL https://api.github.com/repos/<owner>/<repo>/readme \
     -H "Accept: application/vnd.github.raw"                                      # README 原文
curl -s "https://api.github.com/repos/<owner>/<repo>/releases?per_page=1"         # 最近 release
curl -s https://registry.npmjs.org/<package>                                      # npm 包版本/维护时间
curl -sL https://raw.githubusercontent.com/ccusage/ccusage/main/docs/guide/codex/index.md   # 项目文档
```

**标注约定**

- 🟢 **事实**：可直接在该竞品 README / 官方文档 / GitHub API 返回值中读到，已附 URL。
- 🟡 **推断**：由"文档中没有"或间接证据推出，并已写明推断依据；不等于该能力一定不存在。
- ⬜ **未获取**：抓取当日没有拿到可靠数据，不猜数字。
- 涉及"我方"（codex-usage）的事实一律给本仓库内路径或 README 行号。

**我方基线（本仓库，抓取日状态；2026-09-13 晚按开源改造后的实测更新过成本/测试两行）**

| 项 | 值 | 依据 |
|---|---|---|
| 数据源 | 仅 `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`（OpenAI 官方订阅 OAuth 产生的 rollout） | `README.md` 第 3、166 行 |
| 聚合维度 | 会话 / 子代理 / 天 / 模型 / 天×模型 / 家族树（`--by-day` `--by-model` `--family` `--raw`） | `README.md` 第 68–77 行 |
| 图表 | 四档：真图（kitty TGP / Sixel）→ 彩色半块 → 字符画；`CODEX_USAGE_IMAGE_MODE` 可强制档位 | `README.md` 第 111–141 行 |
| 成本来源 | **内置公开定价表（`src/codex_usage/data/pricing.json`，2086 个有价模型，离线可用）为基底**，`CODEX_USAGE_PRICING_FILE` 与本地缓存按 modelId 合并覆盖；`--update-pricing` 从 models.dev / LiteLLM 刷新；无价模型 token 照统计、成本计 $0 并标 `*` | `src/codex_usage/pricing.py`；`docs/pricing.md`；实测 `--doctor` 输出"内置表+自定义文件 … 2086 个模型" |
| 机器可读 | `--json`；`--schema`（由 argparse 定义生成的 JSON 契约）；`--doctor`（环境自检，可 `--json`） | `README.md` 第 81–105 行；`src/codex_usage/selfdoc.py`；`tests/test_selfdoc.py` |
| 工程状态 | Python ≥3.10；`version = "0.1.0"`；单作者 `stofancy`；MIT；CI（3.10–3.13 矩阵）、ruff/mypy、CHANGELOG/CONTRIBUTING/SECURITY/CoC、issue 与 PR 模板均已就位 | `pyproject.toml`；`.github/workflows/ci.yml`；`CHANGELOG.md` |
| 测试 | **129 个用例、7 个测试文件**（合成夹具，不依赖本机数据；含内置定价表覆盖与家族树用例） | `tests/`（`pytest tests/ -q` → 129 passed） |
| 源码规模 | 11 个 Python 模块、约 2345 行 | `src/codex_usage/` |

---

## 1. 事实对照表

共核实 **11 个仓库 + 4 个 npm 包**（`toktrack` 仓库与其 npm 包为同一项目）。分三张表：能力（1.1）、输出与成本（1.2）、工程与生态（1.3）。
所有 star / `pushed_at` / license 均为 **2026-09-13（UTC）** GitHub API 返回值。

### 1.1 覆盖数据源、聚合维度、图表、子代理/家族

| 竞品 | 覆盖的 CLI / 数据源 | 聚合维度 | 图表与可视化 | 子代理 / 父子家族树 |
|---|---|---|---|---|
| **ccusage/ccusage** 🟢 | Claude Code、Codex、OpenCode、Amp、Droid、Codebuff、Hermes、pi-agent、Goose、OpenClaw、Kilo、Kimi、Qwen、GitHub Copilot CLI、Gemini CLI、Antigravity、Grok Build CLI、ZCode（18 个） | 日 / 周 / 月 / 会话 / 5 小时计费块 / statusline；`--by-agent`（JSON-only，agent=数据源）；`--instances`（Claude 按项目） | README 与官方文档中**未见任何官方图表命令**；v18 已移除 `blocks --live`（`docs/guide/live-monitoring.md` 标注 "REMOVED IN v18"）。官方把图表留给社区项目（`docs/guide/community-projects.md` 列了多个 "dashboard with charts" 类项目） | 文档描述了对 Codex MultiAgent V2 subagent rollout 的**计量处理**（用子代理最终继承快照作基线，只计子代理新增用量），但**未见**子代理维度聚合或家族树视图 🟡（推断依据：README/`docs/guide/codex/index.md` 无相关命令） |
| **Piebald-AI/splitrail** 🟢 | Gemini CLI、Qwen Code、Claude Code、Codex CLI、Cline/Roo/Zoo/Kilo Code、GitHub Copilot(+CLI)、OpenCode、Pi Agent、Grok、DeepSeek Harness | README 展示的 MCP 工具体现其维度：daily stats、model usage、cost breakdown、file operations、tool 对比 | CLI 截图 / VS Code 扩展 / 云端 dashboard（README 图片）；未见终端图形协议真图 🟡 | README 未提及子代理或父子家族 🟡 |
| **getagentseal/codeburn** 🟢 | 41 个工具/agent（Claude Code、Cursor、Codex、Gemini、Grok 等） | task / model / tool / project 四个主轴；另可 `optimize`、`guard`、`yield`（产出归因）、`quota`（配额） | `codeburn` TUI + `codeburn web` 本地浏览器图表（15 分钟/小时/天桶、按会话/按模型折线）+ macOS 菜单栏 / Windows 托盘 / Linux GNOME 扩展 | 明确区分主会话与 **subagent sidechain transcript**（在 optimize 分析中把子代理排除出人群统计），但未见家族树视图 🟢（README "Subagent sidechain transcripts are excluded…"） |
| **junhoyeo/tokscale** 🟢 | OpenCode、Claude Code、OpenClaw、Codex CLI、Prime Agent、Sakana Fugu（经 Codex）、GitHub Copilot CLI、Hermes、Gemini、Cursor、Amp、Codebuff、Freebuff、Droid、Pi（15 个） | TUI：overview / models / daily summary / stats；前端 3D 贡献图；全局 leaderboard（需 `submit` 上传） | TUI + 网页仪表盘（README 截图：TUI 四视图、3D 贡献图、Wrapped） | 仅见 Prime Agent "RLM child sessions" 作为数据源说明；未见家族树 🟡 |
| **kenn-io/agentsview** 🟢 | 20+ agent（Claude Code、Codex 等），Claude/Codex 还支持 `s3://` 远程根；Docker 部署 | 会话搜索 / `usage daily` / `stats` / `token-use`；按 agent、日期区间过滤 | Web UI：搜索、活动 heatmap、模型/工具/速度分析、每日花费图 | README 未提及子代理专项视图 🟡 |
| **Mai0313/VibeCodingTracker** 🟢 | Claude Code、Codex、Copilot、Gemini、OpenCode、Cursor、Hermes、Grok、DeepSeek Harness（9 个） | 模型×日期、缓存读/写成本拆分、文件操作（edit/read/write 行数）、工具调用、按 provider 合计 | 交互式 TUI dashboard（可滚动模型列表、实时 CPU/内存、后台增量刷新）+ `--table` / `--text` / `--json`；另有实时配额面板 | Claude 侧递归读取子代理日志（README 数据源段），但**未见**子代理维度或家族树 🟡 |
| **arian-shamaei/anthropometer** 🟢 | Claude Code、Codex CLI、Gemini CLI；Codex 支持直接给 rollout 路径 | 会话 / 上下文窗口内存图 / 逐轮 ledger / 压缩（compaction）事件 / **子代理经济性表** / 文件访问 | 终端 TUI（ratatui）+ 本地生成的 PDF 报告（context map、文件流量、**subagent branch tree**、agent fan-out timeline） | ✅ 明确支持：AGENTS 视图可 drill-in 到子代理自己的窗口；PDF 有 **Subagent branch tree**；Codex subagent rollouts 与 Gemini subagent recordings 均覆盖 🟢 |
| **mag123c/toktrack** 🟢 | Claude Code、Copilot CLI、Codex CLI、Gemini CLI、Qwen Code、OpenCode、PI Agent、Antigravity、Grok CLI（9 个）；支持 SSH 远程 Codex 源快照 | `daily` / `weekly` / `monthly` / `stats` / `audit` | 带 Web 仪表盘的 Rust CLI（README 描述为 "one dashboard"）；未见终端图形协议真图 🟡 | README 未提及 🟡 |
| **JedIV/token-tracker** 🟢 | Claude Code + Codex rollout（明确 `last_token_usage` 增量口径；`cached_input_tokens` 是 `input_tokens` 子集，会相减） | totals / daily time series / 按 model、project、session；MCP server 调用与返回体积 | 本地 Web UI（FastAPI + vanilla JS + Chart.js）：每日 token & 成本折线 | README 未提及 🟡 |
| **jleechanorg/ai-usage-tracker** 🟢 | Claude Code + Codex，但**不直接解析日志**：调用外部 `ccusage` / `ccusage-codex` 命令再合并 | 按天并列（Claude tokens/$ vs Codex tokens/$）+ 日均值 | 无图表（ASCII 表格 + 日均摘要） | 无 🟢（README 未提及子代理） |
| **genewoo/ccusage** 🟢 | fork 自 `ccusage/ccusage`（GitHub API `fork: true`，parent 指向 ccusage/ccusage）；内容即 ccusage 旧版快照 | 同早期 ccusage（daily/monthly/session/blocks） | 同早期 ccusage（无官方图表） | 同早期 ccusage（未提及） |
| **npm `toktrack`**（= mag123c/toktrack） | 同上 | 同上 | 同上 | 同上 |
| **npm `@ccusage/codex`** 🟢 | Codex 专用包，v19.0.0 | — | — | — |
| **npm `@unravel-tech/ccusage-codex`** 🟢 | 第三方 Codex 包（repo 字段仍指向 `ryoppippi/ccusage`），v18.2.2 | — | — | — |

### 1.2 成本来源、机器可读输出

| 竞品 | 成本数据来源 | 机器可读输出 | 有 schema / 自描述契约吗 |
|---|---|---|---|
| **ccusage** 🟢 | LiteLLM 定价数据集：Nix 构建内嵌 locked revision，非 Nix 的 Cargo 构建在构建时按 `flake.lock` 抓取；`--offline` 用预缓存定价；`ccusage.json` 可覆写单价；有定时 workflow 更新定价快照 | `--json`（所有报表类型）；字段结构有专门文档 `docs/guide/json-output.md`；`--no-cost` 可整体去掉成本字段 | 未见 `--schema` 类自描述命令 🟡；`--json` 结构以文档 + 示例描述 🟢 |
| **splitrail** ⬜ | README 未说明定价来源（**未获取**） | 以 **MCP server**（`splitrail mcp`，6 个 tool + 2 个 resource）对外提供数据；README 未提 `--json` 🟡 | 无 CLI schema 🟡 |
| **codeburn** 🟢 | LiteLLM 定价，**每日刷新** | `--format json`（`report` / `status` / `optimize` / `yield` / `quota` 均有）、`export -f json|CSV`；另有 MCP server（2 个 tool） | 无 CLI schema；`yield --format json` 会带 `methodology` 字段说明归因方法 🟢 |
| **tokscale** ⬜ | README 摘要中未见定价来源（**未获取**） | README 图片展示 TUI/前端；JSON 输出未在抓取到的段落确认（**未获取**） | ⬜ |
| **agentsview** 🟢 | JSON 字段含 `has_cost`、`unpriced_models`，说明内置"已定价/未定价"判定；具体定价表来源未在 README 说明（**未获取**） | `--json`、`--format json`；**输出带版本化 schema：`schema_version: 1`** | ✅ 最接近我方 `--schema` 的竞品：JSON 输出有版本化 v1 schema 🟢 |
| **VibeCodingTracker** 🟢 | LiteLLM：模糊模型匹配 + **每日缓存**；`--json` 带 `cost_usd`、`matched_model` 等定价元数据 | `--json`（每模型一行，含成本与匹配到的模型）；`analysis --json` | 无 CLI schema 🟡 |
| **anthropometer** 🟢 | 逐轮 ledger，报告按 **API list price** 计（自述示例：1,945 轮、$1,472 at API list price）；定价表来源未获取 | `turns.jsonl` / `turns.md` 逐轮产物；配套 skill 脚本支持 `--json` | 无 CLI schema 🟡 |
| **toktrack** ⬜ | README 未见（**未获取**） | `daily/weekly/monthly/stats/audit --json` 🟢 | ⬜ |
| **JedIV/token-tracker** 🟢 | 仓库内手编 `prices.json`（按 tool 有 `_default` 兜底），ingest 时计算、每次运行重新套用 | HTTP API（`/api/stats`、`/api/mcp`、`/api/sessions`），非 CLI JSON 契约 | 无 |
| **jleechanorg/ai-usage-tracker** 🟢 | 完全继承 `ccusage` / `ccusage-codex` 的数字 | `--json`（Python 与 JS 两个 CLI 都是） | 无 |
| **genewoo/ccusage** | 同旧版 ccusage（LiteLLM） | `--json` | 无 |
| **我方 codex-usage** | 本机 `~/.cc-switch/model-pricing.json`（doctor 示例：56 个模型）；缺表时成本 $0 并标 `*` | `--json`（会话级，含按模型明细与调用次数）；**`--schema`**（argparse 定义生成的契约，含 `json_output.fields`、`chart_rendering.env`）；**`--doctor`**（环境自检，支持 `--json`） | ✅ 有 |

### 1.3 安装、跨平台、license、活跃度

> star / fork / `pushed_at` / license 字段：**2026-09-13（UTC）** 取自 `https://api.github.com/repos/<owner>/<repo>`；最近 release 取自 `/releases?per_page=1`。npm 版本取自 `https://registry.npmjs.org/<pkg>`。

| 竞品 | 安装方式 | 跨平台（README 明示程度） | License | 活跃度（抓取日 2026-09-13） |
|---|---|---|---|---|
| **ccusage/ccusage** | `npx ccusage@latest`、`bunx`、`pnpm dlx`、`pnpx`、`nix run`；另有 PR 预览包 | README 未列平台矩阵 🟡（npm/Nix 分发，Rust 实现） | README 写 MIT；GitHub API license 字段为 `NOASSERTION`（两者不一致，以 README 为准：MIT） | **18520★** / 829 fork / pushed `2026-09-13` / 最近 release **v20.0.20（2026-08-15）** / open issues 31 |
| **Piebald-AI/splitrail** | Releases 页下载二进制；源码 `cargo run` | 明确自述 cross-platform；README 有 Windows（需 LLVM `lld-link`）与 macOS/Linux 构建说明 | MIT | 223★ / 25 fork / pushed `2026-09-11` / **v3.9.1（2026-09-06）** |
| **getagentseal/codeburn** | `npx codeburn`、`npm i -g codeburn`、`bunx`、`pnpm dlx`、`brew install codeburn`；桌面安装包（dmg/msi/deb/rpm/AppImage） | 明确覆盖：macOS 菜单栏、Windows 托盘（`.msi` 未签名预览）、Linux GNOME 45+ 扩展 | MIT | **10988★** / 825 fork / pushed `2026-09-13` / **v0.9.24（2026-09-04）** / npm 最新 0.9.24（2026-09-04） |
| **junhoyeo/tokscale** | README 强调 `bunx tokscale@latest`（npm 分发） | ⬜（未在抓取段落确认） | MIT（README 徽章 + API） | **5418★** / 440 fork / pushed `2026-09-12` / release 未抓（**未获取**） |
| **kenn-io/agentsview** | `curl .../install.sh \| bash`、Windows PowerShell 一行、`brew install --cask agentsview`、桌面 App、Docker 镜像 | 明确：macOS、Linux、Windows | MIT | **5885★** / 662 fork / pushed `2026-09-12` / **v0.42.0（2026-09-01）** |
| **Mai0313/VibeCodingTracker** | npm（`vibe-coding-tracker` / `@mai0313/vct`）、PyPI（`vibe_coding_tracker`）、crates.io（`vct-cli`）三渠道 | README 未列平台矩阵 🟡 | MIT | 14★ / 6 fork / pushed `2026-09-10` / **v2.7.1（2026-09-09）** |
| **arian-shamaei/anthropometer** | `curl .../install.sh \| sh`（下载预编译二进制，装在 `~/.local`）；另有 crates.io `amtr` | 明确：macOS arm64/x86_64、Linux x86_64/arm64；**未见 Windows** | MIT | 28★ / 0 fork / pushed `2026-09-09` / **v0.5.0（2026-08-17，发布说明含"Codex CLI 与 Gemini CLI sessions attach"）** |
| **mag123c/toktrack** | `npx toktrack`、`brew install toktrack`、`cargo install --git ...` | README **明确列出平台矩阵**：macOS x64/ARM64、Linux x64/ARM64、Windows x64 | MIT | 189★ / 20 fork / pushed `2026-09-08` / npm 最新 **2.17.1（2026-09-04）** |
| **JedIV/token-tracker** | 源码运行：`uv sync` + `make ingest` / `make server`（无发布包） | README 以 macOS launchd 为主（`~/Library/LaunchAgents`）；Linux/Windows 未提及 🟡 | Apache-2.0 | 8★ / 5 fork / pushed **`2026-05-28`**（近 4 个月无提交）/ 无 release / open issues 0 |
| **jleechanorg/ai-usage-tracker** | `pip install ai-usage-tracker`、`npm i -g ai-usage-tracker`；**前置依赖** `ccusage` + `@ccusage/codex` 两个外部 CLI | 未明示；pip/npm 双栈意味着需要 Python + Node 两套运行时 | README 写 MIT；GitHub API license 字段为 `null`（仓库无可识别 LICENSE 文件，两者不一致） | 4★ / 1 fork / pushed `2026-08-18` / open issues 2 |
| **genewoo/ccusage** | 同旧版 ccusage（npx 等） | 同旧版 | README 沿用 ccusage 的 MIT 声明 | **0★** / 0 fork / GitHub API `fork: true`、parent = ccusage/ccusage / pushed **`2026-02-02`**（早于 created_at `2026-02-04`，无自身提交迹象 🟡） |

**npm 包补充（2026-09-13 抓取）**：`@ccusage/codex` v19.0.0（2026-05-19 最后修改，描述已标 "Deprecated compatibility package. Use npx ccusage instead."）；`@ccusage/mcp` v18.0.11（2026-05-19，同样是 v18 世代产物）；`@unravel-tech/ccusage-codex` v18.2.2（2026-03-06）；`toktrack` v2.17.1（2026-09-04）；`codeburn` v0.9.24（2026-09-04）。

**抓取日发现的同类工具（未逐家深挖，供后续补充）**：`JingbiaoMei/Tokdash`（71★，Python，heatmap + 配额）、`sahil87/tu`（4★）、`CDimonaco/tokenpile`（Go CLI+TUI，按 GitHub issue 计费）、`ankit-aglawe/agentwatch`（Rust TUI）、`phuryn/claude-usage`（2218★，Claude 专用 dashboard）、`Javis603/token-monitor`（2116★）、`xiufengsun/TokenTracker`（1595★）等（均来自 2026-09-13 GitHub search API 结果）。

---

## 2. 我方优势（每条都能指到证据）

> 判定原则：只写"竞品文档中确认没有 / 明显更弱"或"本仓库可复算"的项。竞品文档没写 ≠ 一定没有，因此凡属推断均在括号内注明。

### A1. 终端里的**真图**：三档渲染 + 可强制档位，竞品官方图表基本在 Web/桌面端

- 我方：matplotlib 出 PNG → textual-image 送进终端（kitty TGP / Sixel），不支持图形协议时降级彩色半块，未装依赖/被管道重定向/`--ascii` 时用 plotext+termcharts 字符画；`CODEX_USAGE_IMAGE_MODE=auto|tgp|sixel|halfcell|ascii` 可强制；当前档位由 `--doctor` 报出、`--schema` 的 `chart_rendering.env` 可读（`README.md` 第 111–141 行）。
- 竞品对照：ccusage 官方**无图表命令**（v18 还移除了 `blocks --live`，`docs/guide/live-monitoring.md`），官方把图表列为社区项目；codeburn 的图表在 `codeburn web` / 桌面端；tokscale 在 TUI/Web 前端；agentsview 在 Web UI；anthropometer 出的是 **PDF** 报告。抓取到的 11 份 README 中，**没有一家**声明支持 kitty TGP / Sixel 终端真图（🟡 推断：至少未被文档化）。
- 对远程/SSH/纯终端用户这是独占卖点。

### A2. `--schema` + `--doctor`：把"工具怎么用、输出是什么、环境对不对"变成机器可读契约

- 我方：`--schema` 的选项清单**直接由 argparse 定义生成**（不会与实现漂移），并暴露 `json_output.fields` 与 `chart_rendering.env`；`--doctor` 自检数据源、定价表、真图依赖与终端档位、中文字体，支持 `--json`（`README.md` 第 81–105 行；`src/codex_usage/selfdoc.py`，295 行；`tests/test_selfdoc.py` 9 个用例）。
- 竞品对照：抓取范围内只有 **agentsview** 的 `--format json` 带版本化 schema（`schema_version: 1`）与之同类；ccusage 有 `--json` 字段文档但**没有** `--schema` 类自描述命令（🟡 推断）；splitrail 走 MCP server 暴露能力，codeburn 有 MCP（2 tools）但与"本地 CLI 契约"是两条路线。整体上"自描述 + 自检"在竞品中基本是空白区（🟡 推断：以抓取到的 11 份 README 为限）。

### A3. 家族树聚合：`--family` / `--parent` 把主线程与各子代理放同一棵树里

- 我方：`--family --parent 01a083b7` 直接出"主线程 + 各子代理"，子代理按昵称+角色单列，`--raw --type subagent` 可下钻到文件粒度（`README.md` 第 11、31–33 行）。
- 竞品对照：🟢 **anthropometer** 是唯一明确有 subagent tree 的竞品（AGENTS 视图 drill-in + PDF 的 Subagent branch tree，且覆盖 Codex subagent rollouts）；ccusage 只做子代理 **计量**（正确处理 MultiAgent V2 的继承前缀），**没有**家族树视图（🟡）；codeburn 明确把 subagent sidechain 排除出统计人群（🟢 README）；Cline/JedIV/ai-usage-tracker 等未提及。即：家族树在"计量类"工具里仍是少见能力。

### A4. 计量口径可复算：按每轮 `last_token_usage` 增量，而不是被压缩重置污染的累计值

- 我方：按每轮 delta 累加；`README.md` 第 12 行记录实测有会话累计值末值仅为真实消耗的 1/9；`tests/test_stats.py` 用合成夹具把 4 路聚合计总做成**不变量断言**（`test_totals_invariant_across_aggregations`），成本算式写在断言注释里可手算复核。
- 竞品对照：ccusage 的 Codex 文档同样强调 delta 口径；JedIV/token-tracker 的 README 也明确 "We use `last_token_usage` to avoid double-counting"（🟢）。**诚实结论**：delta 口径本身不是我们独占（说明它是业界正确做法），我们的差异在于**逐文件解析 + 子代理单列 + 测试不变量**。写作时不要宣称"只有我们这样做"。

### A5. 默认零网络 + 内置公开定价表：数据不出机器也能算成本

- 我方：解析、聚合、出图全程本地；**内置公开定价表随包发行（`src/codex_usage/data/pricing.json`，2086 个有价模型，离线可用）**，用户可用 `CODEX_USAGE_PRICING_FILE` 与本地缓存按 modelId 覆盖，`--update-pricing` 是唯一联网动作且由用户显式触发（`src/codex_usage/pricing.py`；`docs/pricing.md`；`SECURITY.md` 有写入/联网边界声明）。
- 竞品对照：ccusage 需要 LiteLLM 定价（`--offline` 是显式降级选项，构建期也会抓取定价 revision）；codeburn 的 LiteLLM 定价**每日刷新**；VibeCodingTracker 用 LiteLLM **每日缓存**；splitrail 有云上传能力（默认关闭）；codeburn 桌面端有可选匿名遥测。也就是说"必须联网取价"或"有云/遥测面"是竞品常态，**全默认离线 + 自带定价表**是我们可宣传的隐私差异。

### A6. 契约面完整：stdout/stderr 分离 + 退出码语义 + 129 个不依赖本机数据的测试

- 我方：数据只写 stdout、提示与错误只写 stderr，退出码 `0/1/2/141` 明确（`README.md`），`--json | jq` 不会被噪声打断；7 个测试文件、**129 个用例**（`pytest tests/ -q` → `129 passed`）全部基于合成夹具（`tests/`），`tests/conftest.py` 通过环境变量注入路径，因此 CI 在没有 Codex 数据的机器上也能跑；`.github/workflows/ci.yml` 配置 ubuntu-latest × Python 3.10/3.11/3.12/3.13 矩阵跑 pytest，另有 ruff/mypy job。
- 竞品对照：抓取范围内未系统核实各家测试规模（⬜ 未获取），因此这条只作为"我方工程质量可验证"的素材，不在对照表中下结论。

---

## 3. 我方劣势与风险（诚实清单，按严重度排序）

> 本节每条分三部分：🟢 外部/仓库**事实**、"影响"（**分析推断**，非外部事实）、"可行动"（**建议**，不代表已实现）。

### R1. 生态与用户量差距是数量级级别的（最现实的风险）

- 🟢 事实：抓取日 ccusage **18520★**、codeburn **10988★**、agentsview **5885★**、tokscale **5418★**；我们尚未开源（0★ 基线）。
- 🟡 影响推断：头部仓库已有大量 Issue/文档沉淀，用户迁移成本与"为什么不用 ccusage"的解释成本都在我们这边。
- 可行动：README 开头就要能回答"和 ccusage 差在哪"，并把本文件第 2 节收缩成 2–3 条最硬的差异。

### R2. 分发方式没有 `npx` 的零安装优势

- 🟢 事实：ccusage/codeburn/toktrack/tokscale 都是 `npx <pkg>@latest` 一行即用；splitrail/agentsview/anthropometer 是 `curl | sh` 二进制；VibeCodingTracker 同时上 npm/PyPI/crates。
- 我方：`uv tool install <path>`，需要用户先装 `uv` 与 Python ≥3.10；真图还要 `[image]` 额外依赖（matplotlib + textual-image），且 textual-image **要求 Python ≥3.12**（`pyproject.toml` 第 35–40 行；`README.md` 第 22 行）。
- 影响：TypeScript/Rust 用户第一次尝试的摩擦明显更高。
- 可行动：优先发 PyPI（`uvx codex-usage` / `pipx run`），README 把安装压到一行；把"真图"和"基础表格"在首屏就说清依赖差异。

### R3. 单数据源：竞品普遍 9–41 个工具，我们只解析 Codex rollout

- 🟢 事实：我们只解析 `~/.codex/sessions/**/rollout-*.jsonl`，且只有 OpenAI 官方订阅（OAuth）产生的文件（`README.md` 第 166 行明确列为"已知边界"）。竞品：codeburn 41 个、agentsview 20+、ccusage 18 个、tokscale 15 个、splitrail 14 个（含 Cline/Roo/Zoo/Kilo 四个分支）、toktrack 9 个、VibeCodingTracker 9 个。
- 影响：同时用 Claude Code + Codex 的用户会倾向"一个工具看全部"；我们的深度是单工具的，覆盖率却是单点的。
- 可行动：把"Codex 单点做深"作为定位而非短板；README 明确"不打算做多源聚合"能降低预期错配。

### R4.（已缓解）定价覆盖度：曾经依赖用户本机文件，缺表时静默 $0

- 🟢 事实（抓取日）：当时成本只来自 `~/.cc-switch/model-pricing.json`（`--doctor` 示例显示 56 个模型），没有该文件时"token 照常统计、成本按 $0 计"。ccusage/codeburn/VibeCodingTracker 都内嵌 LiteLLM 定价数据集并自动/每日更新（各家覆盖模型数未逐一核实 ⬜）。
- 🟢 **开源改造已完成**：内置 `src/codex_usage/data/pricing.json`（**2086 个有价模型**，来自 models.dev 公开数据）作为基底，`CODEX_USAGE_PRICING_FILE` 与本地缓存按 modelId **合并覆盖**；`--update-pricing` 可刷新缓存；`--doctor` 报出当前生效来源与模型数（实测："内置表+自定义文件 … 2086 个模型"）。该风险从"新用户第一印象是成本全 0"降级为"次要注意项"。
- 🟡 剩余局限：内置表是**快照**（带 `updated` 字段）；渠道的阶梯价（context > 200k）与 `cache_write` 未计入；公开渠道未收录的模型名在本机仍显示 `$0.00*`；不同转售商报价有差异，内置表按 provider 权威度取价（`docs/pricing.md` 已写明）。
- 可行动：README 首屏给出"成本来源"一节并链接 `docs/pricing.md`；后续可加"成本为 0 时更醒目提示"。

### R5. 平台验证面窄，Windows 没有证据

- 🟢 事实：`--doctor` 示例输出是 Linux（`README.md` 第 95–103 行）；真图依赖终端图形协议探测，README 自己列了 tmux passthrough、格子像素拿不到等边界（第 169 行）；Windows 未在 README/文档中出现；唯一的自动化验证 `.github/workflows/ci.yml` 跑在 **ubuntu-latest**，没有 macOS/Windows job。
- 竞品：toktrack 明确列 macOS/Linux/Windows 矩阵；agentsview/codeburn 三平台覆盖；splitrail 自称 cross-platform 且有 Windows 构建说明。
- 影响：Windows 用户占比不低，没有验证过的声明会被当默认不支持。
- 可行动：至少在 Windows 上跑一遍基础表格与字符画档位并写进 README；真图档位可标"未在 Windows 验证"。

### R6. 文档语言：面向英文开源受众时是门槛

- 🟢 事实：`README.md`、`CHANGELOG.md`、`CONTRIBUTING.md` 等全部为简体中文；仓库内只有 `README.md` 一个 README（抓取日），而 `pyproject.toml` 的 sdist 清单已经引用 `README.zh-CN.md`（第 61 行）——也就是说中英双语文档都还没就位，而清单里已经点名了一个不存在的文件。
- 竞品：tokscale 有 en/ko/ja/zh-cn 四语 README；ccusage/codeburn/agentsview/splitrail 全英文；VibeCodingTracker 有 en/zh-TW/zh-CN。
- 影响：GitHub 首页默认英文读者会直接离开；"中文项目"标签也会影响被引用/收录。
- 可行动：开源首发至少补一份英文 README（可精简版），并把 README.zh-CN.md 与 README.en.md 的关系理顺。

### R7. 单作者维护 + 未发布：作者、版本、发布记录都是 0

- 🟢 事实：`pyproject.toml` 作者只有 `stofancy`（第 13 行），`version = "0.1.0"` 且注释写明"未做过正式发布"（第 7–8 行）；`git remote -v` 为空（尚未配置远端），无 tag、无 release、无外部贡献者。
- 🟢 已具备的治理信号（不应低估）：`.github/workflows/ci.yml`（Python 3.10–3.13 矩阵）、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`ruff.toml`、`mypy.ini`、`tools/` 均已存在（抓取日）。
- 🟡 推断：用户"会不会烂尾 / API 会不会乱变"的顾虑主要来自单作者 + 零发布，而不是缺少治理文件——竞品里 arian-shamaei/anthropometer 同样是单人项目，但已发 crates.io 与预编译二进制，说明"发布"本身就是信任信号。
- 可行动：尽快出第一个 PyPI 版本与 tag，README 顶部放 CI 徽章，把 CHANGELOG 里"`--schema` 属对外契约、破坏性变更走 MAJOR"的承诺显式写进 README。

### R8. 生态集成缺口：MCP / 桌面 / statusline / 编辑器插件全部缺席

- 🟢 事实：splitrail 有 MCP server（6 tools + 2 resources）与 VS Code 扩展；codeburn 有 MCP（2 tools）+ macOS 菜单栏 + Windows 托盘 + GNOME 扩展；ccusage 有 `@ccusage/mcp`（npm 抓取日最新 v18.0.11，2026-05-19 最后修改——注意它停在 v18 世代，主包已到 v20.0.20）、statusline 集成，以及 `docs/guide/community-projects.md` 里一长串 Raycast/Neovim/leaderboard 社区项目；agentsview 有桌面 App 与 Docker。
- 我方：只有 CLI（表格 + 图表 + `--json`/`--schema`/`--doctor`），没有 MCP、没有常驻面板、没有编辑器集成。
- 影响：Agent 工作流里"让模型自己查用量"的场景会被 splitrail/codeburn 先占位。
- 可行动：`--schema` + `--json` 已经是最小 MCP 化的地基；把"`codex-usage mcp`"列进路线图（本文件只做建议，不代表已实现）。

### R9. 与 ccusage 对账口径可能不一致，会被当成 bug

- 🟢 事实：`README.md` 第 168 行自述"与 ccusage 等工具按天对账可能有出入：本工具按会话活动起点归日、按增量计量"。
- 影响：社区最常见的质疑就是"为什么你的数字和 ccusage 不一样"；口径差异必须一句话讲清，否则会被判定为算错。
- 可行动：README 增加"与 ccusage 的差异"小节（归日规则、子代理是否计入、缓存口径），并指向 `tests/test_stats.py` 的不变量测试。

---

## 4. 差异化定位建议

**一句话**：codex-usage 是**面向 Codex 重度用户的本地用量显微镜**——只把 Codex 一件事做透（家族树、可复算口径、终端真图），并把 `--schema`/`--doctor` 做成 Agent 可直接消费的自描述契约，而不是再做一个横跨 40 个工具的聚合面板。

**三条支撑**

1. **头部竞品的 Codex 支持恰恰是它们最薄的部分**：ccusage 的 Codex 文档顶部自标 "Codex log support is experimental while the Codex CLI log format continues to evolve"（🟢 `docs/guide/codex/index.md`），且 18 个源的产品不可能对单一口径做深；我们在这个点上可以做到"唯一把 Codex 家族树与计量正确性讲清楚"。
2. **终端真图 + 零网络是体验层面可截图证明的差异**：竞品图表在 Web/桌面端，只有 anthropometer 出 PDF；`README.md` 里三档对比图（真图 / 半块 / 字符画）是抓取范围内没有第二家能对标的首屏素材。
3. **Agent-native 是我们的空位**：竞品给的要么是"给人看的 dashboard"（codeburn/tokscale/agentsview），要么是"MCP 工具接口"（splitrail/codeburn）或"上下文调试 TUI"（anthropometer）；把**CLI 自描述契约（`--schema`）+ 环境自检（`--doctor`）+ 干净 stdout/stderr/退出码**作为一等公民的，抓取范围内只有我们（agentsview 的 `schema_version: 1` 最接近）。

---

## 附录 A. 未获取 / 待补数据清单

| 项 | 状态 |
|---|---|
| splitrail 定价数据来源 | ⬜ README 未说明 |
| toktrack 定价来源、是否有图表/Web dashboard 细节 | ⬜ README 抓取段落未覆盖 |
| tokscale 定价来源、JSON 输出契约、release 版本 | ⬜ 未在抓取段落确认 |
| anthropometer 定价表来源、是否有 JSON schema | ⬜ |
| 各竞品是否支持 kitty TGP / Sixel 终端真图 | 🟡 11 份 README 均未提及（不等于不存在） |
| 各竞品测试规模 / CI 质量 | ⬜ 未逐家核实 |
| 各竞品 npm/PyPI 下载量与真实用户量 | ⬜ 仅记录版本与维护时间；star 数已注日期 |
| ccusage `--by-agent` 能否下钻到单个子代理 | 🟡 其 JSON 示例中 `agents[].agent` 取值为 `claude`/`codex`（数据源级），非子代理级 |

## 附录 B. 引用 URL 与抓取日期

全部抓取于 **2026-09-13（UTC）**（GitHub API、README raw、npm registry）。

- ccusage：<https://github.com/ccusage/ccusage> ｜ Codex 文档 <https://github.com/ccusage/ccusage/blob/main/docs/guide/codex/index.md> ｜ JSON 文档 <https://github.com/ccusage/ccusage/blob/main/docs/guide/json-output.md> ｜ 社区项目 <https://github.com/ccusage/ccusage/blob/main/docs/guide/community-projects.md> ｜ 已移除的 live monitoring <https://github.com/ccusage/ccusage/blob/main/docs/guide/live-monitoring.md>
- splitrail：<https://github.com/Piebald-AI/splitrail>
- codeburn：<https://github.com/getagentseal/codeburn> ｜ npm <https://www.npmjs.com/package/codeburn>
- tokscale：<https://github.com/junhoyeo/tokscale>
- agentsview：<https://github.com/kenn-io/agentsview>
- VibeCodingTracker：<https://github.com/Mai0313/VibeCodingTracker>
- anthropometer：<https://github.com/arian-shamaei/anthropometer>
- toktrack：<https://github.com/mag123c/toktrack> ｜ npm <https://www.npmjs.com/package/toktrack>
- JedIV/token-tracker：<https://github.com/JedIV/token-tracker>
- jleechanorg/ai-usage-tracker：<https://github.com/jleechanorg/ai-usage-tracker>
- genewoo/ccusage（fork）：<https://github.com/genewoo/ccusage>
- `@ccusage/codex`：<https://www.npmjs.com/package/@ccusage/codex> ｜ `@unravel-tech/ccusage-codex`：<https://www.npmjs.com/package/@unravel-tech/ccusage-codex>
- cc-switch 漏统计相关的 issue（README 第 11 行引用）：<https://github.com/farion1231/cc-switch/issues/5687> —— 抓取日状态 🟢 open，标题 "3.18.0 Codex sync permanently defers completed parent when fork occurs after idle gap"（2026-07-23 创建）。**注意**：issue 标题聚焦"fork 后父会话被永久延迟"，与"子代理会话漏统计"是相关但不等价的表述 🟡，README 引用时建议改成更贴切的措辞。
