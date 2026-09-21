# 定价事实：priority/Fast 档位、倍率来源、`codex-auto-review` 与 `gpt-reserve`

> 任务：T8 调研：priority/Fast 倍率来源与 codex-auto-review 标签语义
> 调研：research-dev ｜ **抓取/复算日期：2026-09-21（UTC）**
> 目的：给「更准的统计」提供外部事实依据，**禁止臆造价格**。每条结论都附一手证据（URL + 原文引用）。
> 标注：🟢 一手事实（官方文档/仓库源码/实测数字）｜🟡 推断或反推（写明依据）｜⬜ 未获取。

---

## 0. 结论摘要（给决策用）

1. 🟢 **`priority` 与 `fast` 是同一个档位**。OpenAI 官方文档原文：「Priority processing was renamed Fast mode on July 30, 2026. … You can use either `service_tier: "priority"` or `service_tier: "fast"` in your API requests to access this functionality.」Codex 侧把 `"fast"` 归一化为请求值 `"priority"`，`"default"` 是"显式标准路由"的哨兵值，`"flex"` 是另一个独立档位（低价、慢）。
2. 🟢 **倍率有官方逐模型价，不必臆造**：OpenAI 官方 pricing 页有 **Fast pricing data / Flex pricing data** 两张独立表。Codex 用到的模型里 `gpt-6-astra`、`gpt-5.6-sol/terra/luna`、`gpt-5.4` 是 **2.0×**，`gpt-5.5` 是 **2.5×**（Fast ÷ Standard）。注意：**Codex 订阅（ChatGPT credits）口径 ≠ API 口径**，官方 Codex Speed 文档写的是 credits 倍率（5.6/5.5=2.5×、5.4=2×、Astra=2.5×）。
3. 🟢 **`codex-auto-review` 是 Codex 自己的「自动审批审查」模型**，在 Codex 官方模型目录里是正式条目，但**没有任何价格元数据**；它被 ccusage 按"日志日期上最新的已知 GPT-5.x(-codex) 模型"改名后计价。**本机 2026-09-12 的 `gpt-5.5` 输出行已证实就是 `codex-auto-review`**（本机日志不存在任何真实 `gpt-5.5` 轮次）。
4. 🟢 **`gpt-reserve` 是真实存在的 Codex 模型标签**（源码 `LUNA_RESERVE_MODEL = "gpt-reserve"`，显示名 "Luna Reserve"，用于普通额度耗尽后的兜底），**官方与 LiteLLM/models.dev 均无其价格**。ccusage 无内置别名 → 成本近似为 0；第三方 agentsview 明确把它映射到 `gpt-5.6-luna` 计价。
5. 🟡 **ccusage 目前对 `gpt-6-astra` 的 Fast 轮次不加成**（其 override 表缺 astra），用官方价反推本机 2026-09-12 的账，差额正好等于 luna + auto-review 两个模型的 priority 加成 —— 也就是说 ccusage 当天约**少算 $52.2**（astra priority 部分的 1× 差额）。这是"我们做得更准"最直接的证据点。
6. **建议**：按轮次归因 tier → 用官方 Fast 表逐模型取倍率（而不是统一 2×）→ 无官方价的两个标签（`codex-auto-review`、`gpt-reserve`）做**显式标注的**别名映射，输出里保留原标签并标 `assumed`。

---

## 1. `thread_settings_applied` / `service_tier` 到底代表什么

### 1.1 官方口径：Fast mode = 原 priority processing 🟢

> 来源：<https://platform.openai.com/docs/guides/priority-processing.md>（标题 `# Fast mode`），抓取日 **2026-09-21**

原文引用：

> "Priority processing was renamed Fast mode on July 30, 2026. We also increased the speed at which Fast mode operates for `gpt-5.6-sol` to make it up to 2.5× faster than Standard processing. **You can use either `service_tier: "priority"` or `service_tier: "fast"` in your API requests to access this functionality.**"

> "Fast mode charges a per-token premium over Standard processing. See the [pricing page](https://developers.openai.com/api/docs/pricing?latest-pricing=fast) for details and supported models."

> "Cached input discounts still apply to Fast mode requests."

> "…slow Fast mode requests to standard speeds and **charge standard rates**. When this happens, the response contains `service_tier: "default"`."

> "To view Fast mode requests in the usage dashboard, select the option to group by service tier. **For GPT-5.6 and earlier models, these requests appear as `priority` even when you specify `fast`.**"

结论 🟢：`priority` 与 `fast` 是同一件事的两个拼写；`default` 表示按标准速率计费（可能是客户端显式选择，也可能是服务端把 Fast 请求降级后的响应值）；这不是"三档定价"，而是"标准 / Fast（原 priority）/ Flex"三条计费路径。

补充 🟢（Codex 产品侧）：<https://learn.chatgpt.com/docs/agent-configuration/speed.md>（抓取日 2026-09-21）原文：

> "Codex offers the ability to increase the speed of the model for increased credit consumption. For GPT-5.6, GPT-5.5, and GPT-5.4, Fast mode increases model speed by 1.5x. GPT-5.6 and GPT-5.5 consume credits at 2.5x the Standard rate; GPT-5.4 consumes credits at 2x the Standard rate."
> "Use `/fast on`, `/fast off`, or `/fast status` in the CLI… You can also persist the default with `service_tier = "fast"` plus `[features].fast_mode = true` in `config.toml`."
> "**Fast mode is a ChatGPT credit feature.** With an API key, Codex uses API token pricing instead, and ChatGPT credit multipliers don't apply. **API Priority processing has its own billing rate; for GPT-5.6, it costs 2x the Standard API token rate.**"

### 1.2 Codex 实现侧：档位枚举与请求值 🟢

> 来源：`openai/codex` 源码（`main` 分支，抓取日 2026-09-21）
> <https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/config_types.rs>

```rust
pub enum ServiceTier { Fast, Flex }

/// Request/config sentinel for explicit standard routing.
pub const SERVICE_TIER_DEFAULT_REQUEST_VALUE: &str = "default";

impl ServiceTier {
    pub const fn request_value(self) -> &'static str {
        match self {
            Self::Fast => "priority",
            Self::Flex => "flex",
        }
    }
    pub fn from_request_value(value: &str) -> Option<Self> {
        match value {
            "fast" | "priority" => Some(Self::Fast),
            "flex" => Some(Self::Flex),
            _ => None,
        }
    }
}
```

另外 `codex-rs/protocol/src/openai_models.rs` 有 `pub const SPEED_TIER_FAST: &str = "fast";`（legacy 拼写）。

Codex 官方 PR <https://github.com/openai/codex/pull/23537>（已合并 2026-05-20）描述三种状态必须区分：无显式 tier / 显式 `default` / 目录档位 `priority`、`flex`；并明确「normalized legacy config spelling so `fast` in `config.toml` still materializes as the runtime/request id `priority`」。

Codex 模型目录 <https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json>（抓取日 2026-09-21）里每个模型的 `service_tiers` 只有 id `priority`（`gpt-5.6-sol` 另有 `ultrafast`），描述是 "1.5x speed, increased usage" —— **目录里没有任何价格字段**（9 个模型的 `cost`/`price` 字段为空）。

### 1.3 `thread_settings_applied` 事件结构与 ccusage 的读法 🟢

本机 rollout 里的事件形态（实测样本，字段已截断）：

```json
{"type": "thread_settings_applied", "thread_id": "01a088bd-…",
 "thread_settings": {"model": "gpt-6-astra", "model_provider_id": "openai",
                     "service_tier": "default", "approval_policy": "never", …}}
```

ccusage 的 Rust 解析器（<https://raw.githubusercontent.com/ccusage/ccusage/main/rust/adapters/codex/src/parser.rs>，抓取日 2026-09-21）：

```rust
if payload.payload_type.as_deref() == Some("thread_settings_applied") {
    // A settings event that carries no `service_tier` at all says nothing
    // about the tier, so the previous one stands. Codex emits such events
    // for auto-review threads. A tier that is present but unrecognized is
    // different: it means the tier changed to something unknown, so the
    // stale value must not be inherited.
    if let Some(recorded) = payload.thread_settings.as_ref()
        .and_then(|settings| settings.service_tier.as_deref())
    { *current_service_tier = codex_service_tier(recorded); }
    return Ok(());
}
...
fn codex_service_tier(value: &str) -> Option<CodexServiceTier> {
    match value {
        // Both spellings mean non-priority pricing… (Codex Desktop writes "standard")
        "default" | "standard" => Some(CodexServiceTier::Standard),
        "fast" | "priority" => Some(CodexServiceTier::Fast),
        _ => None,
    }
}
```

🟡 **推断**：`flex` 落在 `_ => None`，即 ccusage 把 Flex 当"未知档位"处理（不套 Fast 倍率，也不报错）。本机样本里没有 flex。

### 1.4 本机实测（独立复核）🟢

口径：扫描 `~/.codex/sessions/2026/09/{10,11,12,13}/*.jsonl`（132 个文件），逐行解析，按文件顺序维护"最近的 `thread_settings_applied`"，统计事件与 token。

| 项 | 值 |
|---|---|
| `thread_settings_applied` 总数 | **742** 条 |
| `service_tier` 分布 | `default` **681** / `priority` **61** / 缺失 **0** |
| 客户端版本 | `cli_version: 0.153.0`（`session_meta`） |
| 本机 `~/.codex/config.toml` | `service_tier = "default"`（无 `[features].fast_mode`） |

⚠️ 与 Lead 提供的数字（741 条 / 61 条 priority）差 **1 条**：priority 一致，总数差 1，可能是扫描窗口或对同一文件重复计数的口径差；以 61 为准没有争议。

🟢 因为 `config.toml` 是 `default`，ccusage 的 `--speed auto` 对"日志里没有 tier 标记的轮次"会按 Standard 处理 —— 这一点在下面第 2.6 节的成本反推里被独立验证。

---

## 2. Fast/priority 倍率从哪来（可直接落表的数据）

证据优先级：**OpenAI 官方 Fast 价目表 > 官方 Codex 文档 > LiteLLM 数据 > models.dev > 第三方实现**。

### 2.1 官方逐模型 Fast 价（一手，最权威）🟢

> 来源：<https://platform.openai.com/docs/pricing.md>，抓取日 **2026-09-21**。原文表头：`### Standard pricing data` / `### Fast pricing data` / `### Flex pricing data`。

**Standard（短上下文，USD / 1M tokens）**

| Model | Input | Cached input | Cache writes | Output |
|---|---|---|---|---|
| gpt-6-astra | $10.00 | $1.00 | $12.50 | $50.00 |
| gpt-5.6-sol | $4.00 | $0.40 | $5.00 | $20.00 |
| gpt-5.6-terra | $2.00 | $0.20 | $2.50 | $12.00 |
| gpt-5.6-luna | $0.20 | $0.02 | $0.25 | $1.20 |
| gpt-5.5 (<272K) | $5.00 | $0.50 | - | $30.00 |
| gpt-5.4 (<272K) | $2.50 | $0.25 | - | $15.00 |
| gpt-5.4-mini | $0.75 | $0.075 | - | $4.50 |
| gpt-5.2 | $1.75 | $0.175 | - | $14.00 |
| gpt-5.1 / gpt-5 | $1.25 | $0.125 | - | $10.00 |

**Fast（短上下文，USD / 1M tokens）**

| Model | Input | Cached input | Cache writes | Output | Fast ÷ Standard |
|---|---|---|---|---|---|
| gpt-6-astra | $20.00 | $2.00 | $25.00 | $100.00 | **2.0×** |
| gpt-5.6-sol | $8.00 | $0.80 | $10.00 | $40.00 | **2.0×** |
| gpt-5.6-terra | $4.00 | $0.40 | $5.00 | $24.00 | **2.0×** |
| gpt-5.6-luna | $0.40 | $0.04 | $0.50 | $2.40 | **2.0×** |
| gpt-5.5 (<272K) | $12.50 | $1.25 | - | $75.00 | **2.5×** |
| gpt-5.4 (<272K) | $5.00 | $0.50 | - | $30.00 | **2.0×** |
| gpt-5.4-mini | $1.50 | $0.15 | - | $9.00 | 2.0× |
| gpt-5.2 | $3.50 | $0.35 | - | $28.00 | 2.0× |
| gpt-5.1 / gpt-5 | $2.50 | $0.25 | - | $20.00 | 2.0× |

官方文字确认（同一页 FAQ）：

> "**For GPT-5.6 Sol, Fast mode costs twice the corresponding Standard rate.** Short-context requests cost $8 per 1 million input tokens and $40 per 1 million output tokens; long-context requests cost $16 per 1 million input tokens and $60 per 1 million output tokens."

> "Fast mode is unavailable for GPT-6 Astra with EU data residency. Use Standard processing for those requests."

> "Regional processing (data residency) endpoints are charged a 10% uplift for models released on or after March 5, 2026…"

**长上下文（>272K input）Fast 价**（同一 Fast 表，ASTRA/Sol/Terra/Luna 有）：astra $40 / $4 / $50 / $150；sol $16 / $1.60 / $20 / $60；terra $8 / $0.80 / $10 / $36；luna $0.80 / $0.08 / $1.00 / $3.60。本机单轮输入远低于 272K，短上下文价即足够。

**Flex 价**（供对照，是 Standard 的 0.5×）：astra $5 / $0.50 / $6.25 / $25.00；5.6-sol $2 / $0.20 / $2.50 / $10；5.6-terra $1 / $0.10 / $1.25 / $6；5.6-luna $0.10 / $0.01 / $0.125 / $0.60；5.5 $2.50 / $0.25 / - / $15.00。

⬜ **未获取**：`gpt-5.3-codex`、`gpt-5.2-codex`、`gpt-5.1-codex`、`codex-auto-review`、`gpt-reserve` 在官方 Fast 表中**都没有行** → **无公开 Fast 价**。

### 2.2 订阅（ChatGPT credits）口径 ≠ API 口径 🟢

> 来源：<https://learn.chatgpt.com/docs/agent-configuration/speed.md> 与 <https://learn.chatgpt.com/docs/pricing.md>，抓取日 2026-09-21

- credits 倍率：**GPT-5.6 / GPT-5.5 = 2.5×**，**GPT-5.4 = 2×**，**GPT-6 Astra = 2.5×**（speed.md 原文见 1.1；pricing.md 原文：「Fast mode applies a 2.5x multiplier to Astra's Standard rate.」）。
- API 口径：GPT-5.6 Sol = 2×（见 2.1）。
- pricing.md 的 token 表单位是 **credits / 1M tokens**（GPT-6 Astra 250/25/1250，GPT-5.6 Sol 100/10/500，Terra 50/5/300，Luna 5/0.5/30，GPT-5.5 125/12.5/750，GPT-5.4 62.5/6.25/375），**不是美元**。

🟡 **推断**：这就是为什么不同工具算出的"Fast 倍率"不一样 —— 用 credits 口径（订阅账单）是 2.5×，用 API 等价口径是 2×（5.6）/2.5×（5.5）/2×（5.4）。任何工具都必须先声明自己报的是哪一种；本仓库既然按 API 等价美元计价，就应当采用 2.1 的官方 Fast 表。

### 2.3 LiteLLM 快照里到底有没有 priority/flex 字段 🟢

快照：`.scratch/litellm.json`（本机 2026-09-21 19:07 保存；上游 `model_prices_and_context_window.json` 在 GitHub 上的最后提交为 `b1a61f510c90`，`2026-09-13T04:13:52Z`，`gh api repos/BerriAI/litellm/commits?path=…`）。⬜ 本仓库未留下该快照的下载命令行，URL 依据上游文件名与 `LiteLLMPricingFetcher` 的惯例，**标记为待确认**。

| 字段族 | 出现次数（键名计数） | 说明 |
|---|---|---|
| `input_cost_per_token_priority` | 116 | 模型条目数（含 provider 前缀） |
| `output_cost_per_token_priority` | 114 | |
| `cache_read_input_token_cost_priority` | 112 | |
| `cache_creation_input_token_cost_priority` | 17 | |
| `input_cost_per_token_above_272k_tokens_priority` 等长上下文变体 | 27 | 与官方 272K 分档一致 |
| `*_above_200k_tokens_priority` 等 | 8–9 | 其他 provider 的分档 |
| `*_flex`（全部 flex 变体） | 45 个条目（裸名 33） | Standard 的 0.5× |
| `provider_specific_entry.fast` | **仅 2 个模型**：`claude-opus-5`、`claude-opus-4-8`（值 2.0） | 与 Codex 模型无关 |
| `gpt-reserve` / `codex-auto-review` | **0** | 两个标签都不在 LiteLLM 表中 |

**裸名（无 provider 前缀）含 priority 价的有 53 个**，其中 Codex 相关的与我们相关的部分：

| 裸名 | standard in/out/cache | priority in/out/cache | 倍率 |
|---|---|---|---|
| gpt-5.6-luna | 2e-7 / 1.2e-6 / 2e-8 | 4e-7 / 2.4e-6 / 4e-8 | 2.00× |
| gpt-5.6-sol | 4e-6 / 2e-5 / 4e-7 | 8e-6 / 4e-5 / 8e-7 | 2.00× |
| gpt-5.6-terra | 2e-6 / 1.2e-5 / 2e-7 | 4e-6 / 2.4e-5 / 4e-7 | 2.00× |
| gpt-5.6 | 4e-6 / 2e-5 / 4e-7 | 8e-6 / 4e-5 / 8e-7 | 2.00× |
| gpt-6-astra | 1e-5 / 5e-5 / 1e-6 | 2e-5 / 1e-4 / 2e-6 | 2.00× |
| gpt-5.5 | 5e-6 / 3e-5 / 5e-7 | 1.25e-5 / 7.5e-5 / 1.25e-6 | **2.50×** |
| gpt-5.4 | 2.5e-6 / 1.5e-5 / 2.5e-7 | 5e-6 / 3e-5 / 5e-7 | 2.00× |
| gpt-5.3-codex | 1.75e-6 / 1.4e-5 / 1.75e-7 | 3.5e-6 / 2.8e-5 / 3.5e-7 | 2.00× |
| gpt-5.2-codex | 1.75e-6 / 1.4e-5 / 1.75e-7 | 3.5e-6 / 2.8e-5 / 3.5e-7 | 2.00× |
| gpt-5.1-codex | 1.25e-6 / 1e-5 / 1.25e-7 | 2.5e-6 / 2e-5 / 2.5e-7 | 2.00× |
| gpt-5-codex | 1.25e-6 / 1e-5 / 1.25e-7 | **无** | 无公开 priority 行 |
| gpt-5 | 1.25e-6 / 1e-5 / 1.25e-7 | 2.5e-6 / 2e-5 / 2.5e-7 | 2.00× |

🟢 **交叉验证**：LiteLLM 的 standard 价与官方 Standard 表逐项一致（luna 0.2/1.2/cache 0.02、sol 4/20/0.4、terra 2/12/0.2、astra 10/50/1、5.5 5/30/0.5、5.4 2.5/15/0.25），priority 价与官方 Fast 表一致（含 5.5 = 2.5× 这个"例外"）。→ **LiteLLM 快照可以放心用来落表**（前提是记录快照日期）。

### 2.4 models.dev 快照：**没有** priority/flex 价 🟢

快照：`.scratch/models.dev.json`（本机 2026-09-21 19:07 保存；上游 <https://models.dev/api.json>，抓取日 2026-09-21，HTTP 200，ETag `"4118ac46a2dc3c2c548c048fe79efaba"`）。

- `cost` 结构只有：`input` / `output` / `cache_read` / `cache_write` / `reasoning`，以及 `tiers: [{input, output, cache_read, cache_write, tier:{type:"context", size:272000}}]` 和 `context_over_200k`。
- 🟢 `tiers` 的 `tier.type` 一律是 **`context`**（上下文长度分档），**不是** service tier；全库 grep 不到 priority/flex 价字段。
- 🟢 `codex-auto-review`、`gpt-reserve` 在 models.dev 中**均不存在**。
- 例：`openai/gpt-5.6-luna` cost = `{input:0.2, output:1.2, cache_read:0.02, cache_write:0.25, tiers:[{input:0.4,…,size:272000}]}` —— 与官方 Standard 表一致。

结论：**若内置表用 models.dev 生成，就必须自己叠加 Fast 倍率；models.dev 本身给不出 priority 价。**

### 2.5 ccusage 的倍率来自哪里（源码）🟢

ccusage 有两条实现路径，倍率来源不同：

**(a) 当前 Rust 实现（v20 主分支）：自维护 override 表 + 默认 1.0**

> <https://raw.githubusercontent.com/ccusage/ccusage/main/rust/crates/ccusage-core/src/fast-multiplier-overrides.json>

```json
{
  "exact": {
    "gpt-5.6-sol": 2.0, "gpt-5.6-terra": 2.0, "gpt-5.6-luna": 2.0,
    "gpt-5.5": 2.5, "gpt-5.4": 2.0, "gpt-5.3-codex": 2.0
  },
  "normalized_prefix": { "claude-opus-4-6": 6.0, "claude-opus-4-7": 6.0, "claude-opus-4-8": 2.0 }
}
```

`rust/crates/ccusage-core/src/pricing.rs` 里 `Pricing::empty()` 的 `fast_multiplier: 1.0`，只有命中 override 才改写 —— **表外的模型（如 `gpt-6-astra`）不会被加成**。

**(b) 旧的 TS 实现（apps/codex/src/pricing.ts，PR #996 引入）：provider_specific_entry.fast，缺省 2×**

> <https://github.com/ccusage/ccusage/pull/996/files>

```ts
const CODEX_FAST_FALLBACK_MULTIPLIER = 2;
const speedMultiplier = this.speed === 'fast'
  ? (pricing.provider_specific_entry?.fast ?? CODEX_FAST_FALLBACK_MULTIPLIER)
  : 1;
```

而 LiteLLM 里 `provider_specific_entry.fast` 只存在于两个 Claude 模型（见 2.3）→ 对 Codex 模型它永远走 2× 兜底。ccusage 文档（`docs/guide/codex/index.md`，抓取日 2026-09-21）自述：

> "Fast pricing uses a model-specific multiplier only when one is available; otherwise, ccusage keeps standard pricing rather than inventing a rate."

🟡 **两条路径行为不一致**（TS 兜底 2× vs Rust 默认 1×）。实际本机输出的行为符合 **Rust 的 1× 兜底**（见 2.6）。

### 2.6 实测反推：验证 ccusage 的实际加成（本机 2026-09-12）🟡（有强证据的推断）

素材：
- `.scratch/ccusage.json`（本机 ccusage 输出快照，2026-09-21）：`2026-09-12` 行 `costUSD = 853.8963367599999`，各模型 `inputTokens`（= 净输入，见下）、`cacheReadTokens`、`outputTokens`。
- 我方独立扫描（见 1.4）得到同日各 (模型, tier) 的 token 量，其中 **priority 轮次**：`gpt-6-astra` 297 轮 / `gpt-5.6-luna` 31 轮 / `codex-auto-review` 50 轮。

核算（用 ccusage 自己的 token 数 × LiteLLM standard 价）：

| 模型 | standard 成本 |
|---|---|
| gpt-5.5（= auto-review 改名） | 27.681195 |
| gpt-5.6-luna | 21.449479 |
| gpt-5.6-sol | 51.145391 |
| gpt-5.6-terra | 14.239083 |
| gpt-6-astra | 736.191562 |
| **合计（有价模型）** | **850.706711** |
| ccusage 实际 costUSD | **853.896337** |
| 差额 | **+3.189626** |

用我方按 tier 拆分的 token 量算 priority **加成**：

| 模型（priority 轮次） | 标准成本 | 若 2×/2.5× 的加成 |
|---|---|---|
| gpt-6-astra（297 轮） | 52.166 | 若 2× 则 +52.166 |
| gpt-5.6-luna（31 轮） | 0.122 | +0.122 |
| codex-auto-review→gpt-5.5（50 轮） | 2.048 | 2.5× → **+3.071** |
| **luna + auto-review 加成合计** | | **+3.193** |

🟡 **结论（强推断）**：3.193 ≈ 实测差额 3.190（差 0.003，来自归日/归因的微小差异）→
1. ccusage **确实**按 Fast 给 luna（2.0×）和 auto-review 映射后的 gpt-5.5（2.5×）加成；
2. ccusage **没有**给 `gpt-6-astra` 的 297 个 priority 轮次加成（若加成，差额应约 +55.4）→ 与 2.5(a) 的 override 表缺 astra 完全吻合；
3. ccusage 对 **`gpt-reserve` 的成本贡献≈0**（若按 luna 2× 计会额外 +3.23，与实测不符）。

🟢 结论 3 的辅助证据：`gpt-reserve` 在 ccusage 的 `model_aliases.rs` 中**没有内置别名**（该表只从环境变量 `CCUSAGE_MODEL_ALIASES` 读取，默认空）。

⚠️ **严谨性提示**：第 2.6 节的反推混合了两套 token 口径 —— 「标准的 850.71」用的是 ccusage 自己的 token 数，而「priority 加成」用的是我方按 tier 拆分的 token 数（两者在 09-12 相差约 2%，原因见 3.3）。因此 3.193 vs 3.190 是**量级级的强印证**（足以排除"astra 有加成"和"reserve 有计价"这两个假设），不是精确闭环。要拿到精确闭环，需要按 ccusage 完全相同的归日/replay 规则复算，或直接读 ccusage 源码的单测期望值。

**这对我们的意义**：同样的日志，按官方 Fast 表算，2026-09-12 仅 astra 一项就应多计 **$52.2**（约当天总成本的 6.1%），这还没算 `gpt-reserve` 的 58.0M tokens。

### 2.7 影响最大的口径问题：`inputTokens` 是净输入 🟢

用 ccusage.json 自洽验证：`gpt-5.5` 行 `inputTokens 3,595,007 + cacheReadTokens 16,871,680 + outputTokens 42,344 = 20,509,031 = totalTokens` ✓。
即 ccusage 的 `inputTokens` **已扣除缓存读**（= 我方"净输入"），与本仓库 README 的"净输入 = 毛输入 − 缓存读"一致。做对账时不要重复扣减。

---

## 3. `codex-auto-review` 与 `gpt-reserve`

### 3.1 `codex-auto-review` 在 Codex 侧的真实含义 🟢

Codex 官方模型目录里它是一个**正式条目**（<https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json>，抓取日 2026-09-21）：

```json
{
  "slug": "codex-auto-review",
  "display_name": "Codex Auto Review",
  "description": "Automatic approval review model for Codex.",
  "service_tiers": [{"id": "priority", "name": "Fast", "description": "1.5x speed, increased usage"}],
  "default_service_tier": null
}
```

要点：
- 🟢 display name 是 **"Codex Auto Review"**，用途是 Codex 的**自动审批审查**（与本机 `config.toml` 的 `approvals_reviewer = "auto_review"` 对应）。
- 🟢 目录里**没有价格字段**（`cost`/`price` 全空），也没有指向任何公开模型 id 的映射。
- 🟢 社区佐证：`openai/codex` issue [#20981](https://github.com/openai/codex/issues/20981)（2026-05-04 创建，抓取日仍 **open**）标题即 "`codex-auto-review` in OTel token usage metrics is hard to map to official model pricing"；issue 正文：「`codex-auto-review` does not appear to be an official public OpenAI model name in the pricing documentation… dashboard authors have to either drop these samples, guess a mapping, or assign a fallback price」。评论（@rebroad, 2026-08-04）："It is intentionally a hidden routing alias with `model: null` and `model_provider: null`; the Codex source does not map it to a stable public model."
- 🟢 官方**从未**给出它的计费身份 → **无公开价**。

### 3.2 ccusage 怎么映射它 🟢

> <https://raw.githubusercontent.com/ccusage/ccusage/main/rust/adapters/codex/src/parser.rs>

```rust
const CODEX_AUTO_REVIEW_MODEL: &str = "codex-auto-review";
const CODEX_AUTO_REVIEW_FALLBACKS_JSON: &str = include_str!("codex-auto-review-fallbacks.json");
...
fn codex_log_model_fallback(model: &str, timestamp: &str) -> Option<&'static str> {
    if model != CODEX_AUTO_REVIEW_MODEL { return None; }
    let Some(date) = codex_timestamp_date(timestamp) else { return Some("gpt-5"); };
    Some(codex_auto_review_fallback_models().iter()
        .find_map(|fallback| (date >= fallback.released_on).then_some(fallback.model))
        .unwrap_or("gpt-5"))
}
```

映射表（<https://raw.githubusercontent.com/ccusage/ccusage/main/rust/adapters/codex/src/codex-auto-review-fallbacks.json>，抓取日 2026-09-21）**按发布日降序**：

```json
[{"releasedOn":"2026-04-23","model":"gpt-5.5"},
 {"releasedOn":"2026-03-05","model":"gpt-5.4"},
 {"releasedOn":"2026-02-05","model":"gpt-5.3-codex"},
 {"releasedOn":"2025-12-11","model":"gpt-5.2-codex"},
 {"releasedOn":"2025-11-13","model":"gpt-5.1-codex"},
 {"releasedOn":"2025-09-15","model":"gpt-5-codex"},
 {"releasedOn":"2025-08-07","model":"gpt-5"}]
```

- 🟢 生成逻辑在 `nix/tools/models-dev-gen/gen.ts`：候选只接受 `gpt-5`、`gpt-5-codex`、`/^gpt-5\.\d+$/`、`/^gpt-5\.\d+-codex$/` —— **`gpt-5.6-sol/terra/luna` 这类带后缀的新模型不在候选中**，所以即使 models.dev 有 5.6 系，也不会进这张表。
- 🟢 结果：**2026-09-12 的日志会映射到 `gpt-5.5`**（列表第一个 `releasedOn <= 日期`）。

### 3.3 证实：ccusage 输出里的 `gpt-5.5` 就是本机的 `codex-auto-review` 🟢（三方一致）

| 证据 | 内容 |
|---|---|
| ① 源码机制 | `is_fallback_model` 只在 `model == "codex-auto-review"` 时置真；输出里 `gpt-5.5` 行带 `"isFallback": true`（`.scratch/ccusage.json`） |
| ② 本机模型集合 | 独立扫描 2026-09-10~13 的全部 rollout，出现过的模型只有 `gpt-5.6-luna`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-6-astra`、`codex-auto-review`、`gpt-reserve` —— **没有任何真实 `gpt-5.5` 轮次** |
| ③ 数字对账 | 本机 `codex-auto-review`：净输入 **3,621,101** / 缓存读 **17,254,144** / 输出 **42,558**（299 轮）；ccusage `gpt-5.5`（2026-09-12）：**3,595,007** / **16,871,680** / **42,344**（total 20,509,031）→ 偏差 ~2%，来自归日/子代理 replay 处理差异 |

**判定：证实（高置信度）**。差异部分（~2%）来源：ccusage 按事件时间戳归日与我方按文件目录/本地日的差别，以及 ccusage 对子代理 replay 前缀的跳过逻辑；⬜ 未获取 ccusage 快照的具体版本号与 `--timezone` 参数。

### 3.4 `gpt-reserve` 是什么 🟢

> <https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/model_catalog.rs>

```rust
pub(crate) const LUNA_RESERVE_MODEL: &str = "gpt-reserve";
pub(crate) const LUNA_MODEL: &str = "gpt-5.6-luna";

pub(crate) fn model_display_name(model: &str) -> &str {
    if model.eq_ignore_ascii_case(LUNA_RESERVE_MODEL) { "Luna Reserve" } else { model }
}
```

> <https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/error.rs>

```rust
// Reserve is a fallback for exhausted ordinary usage, so keep the standard
// promo/plan recovery copy below instead of suggesting another model.
```

- 🟢 它是 **"Luna Reserve"**：普通额度耗尽后的兜底路由；在 Codex 模型目录（`models.json`）里**没有条目**、也**没有价格**。
- 🟢 本机确有大量使用：2026-09-12 共 **375 轮**，净输入 1,831,531 / 缓存读 56,109,568 / 输出 106,760（≈58.0M tokens）。
- 🟢 第三方处理先例（kenn-io/agentsview，<https://raw.githubusercontent.com/kenn-io/agentsview/main/internal/pricing/supplemental.go>，抓取日 2026-09-21）：

```go
// GPT56LunaCanonical is the catalog id for Codex Luna Reserve (gpt-reserve).
GPT56LunaCanonical  = "gpt-5.6-luna"
GPTReserveModelName = "gpt-reserve"
```

- 🟢 LiteLLM / models.dev **均无** `gpt-reserve`；ccusage 无内置别名（见 2.6）→ **ccusage 对它计 0 成本**（实测反推支持）。
- ⬜ **未获取**：OpenAI 官方对 Reserve 用量的计费说明。pricing.md / speed.md 均未提及 `gpt-reserve`。

---

## 4. 我们要更准该怎么算（明确建议）

### 4.1 tier 归因（逐轮，而不是按会话/按天）

1. 逐文件顺序维护 `current_tier`：遇到 `event_msg.payload.type == "thread_settings_applied"` 且 `thread_settings.service_tier` 非空 → 更新；**带 `service_tier` 的未知值（如 `flex`）按"未知"处理并停止沿用旧值**（与 ccusage 的注释语义一致，但建议把未知值单独暴露出来而不是静默当标准价）。
2. 轮次（`token_count`）按其发生时的 `current_tier` 归属；`priority` / `fast` → Fast 价；`default` / `standard` → Standard 价。
3. 文件开头/无标记的轮次（本机 09-12 有相当比例）→ 回退读 `~/.codex/config.toml` 的 `service_tier`（本机为 `default`；ccusage 的 `--speed auto` 也是这个行为）。
4. 建议在输出中**报告 tier 覆盖率**：已标记轮次数 / 总轮次数、各 tier 的 token 与成本占比。本机 09-10~13 的样本是 742 条 settings（default 681 / priority 61），priority 轮次集中在 09-12。

### 4.2 倍率取值（推荐直接用官方 Fast 表，逐模型）

| 模型 | Standard（官方） | Fast（官方） | 倍率 | 证据 |
|---|---|---|---|---|
| gpt-5.6-luna | 0.2 / 0.02 / 1.2 | 0.4 / 0.04 / 2.4 | 2.0× | pricing.md Fast 表 🟢 |
| gpt-5.6-terra | 2 / 0.2 / 12 | 4 / 0.4 / 24 | 2.0× | 同上 🟢 |
| gpt-5.6-sol | 4 / 0.4 / 20 | 8 / 0.8 / 40 | 2.0× | 同上 🟢 |
| gpt-6-astra | 10 / 1 / 50 | 20 / 2 / 100 | 2.0× | 同上 🟢 |
| gpt-5.5 | 5 / 0.5 / 30 | 12.5 / 1.25 / 75 | **2.5×** | 同上 🟢 |
| gpt-5.4 | 2.5 / 0.25 / 15 | 5 / 0.5 / 30 | 2.0× | 同上 🟢 |
| gpt-5.3-codex / 5.2-codex / 5.1-codex | LiteLLM 有 standard | 官方 Fast 表**无行**；LiteLLM priority 有值（=2.0×） | 2.0×（低置信） | LiteLLM 🟢 + 官方缺行 ⬜ |
| gpt-5-codex | LiteLLM 有 standard | **无任何 priority/flex 价** | **无公开价，建议不臆造**（保持 Standard 并在输出标注） | LiteLLM ❌、官方 ❌ |
| codex-auto-review | 无 | 无 | **无公开价**；如需计价按 4.3 的别名方案并标 `assumed` | 官方目录无价 🟢 |
| gpt-reserve | 无 | 无 | **无公开价**；别名方案见 4.3（标 `assumed`） | 官方/LiteLLM/models.dev 均无 🟢 |

**取值原则（建议写进实现）**：倍率优先用官方表；**不要**用"统一 2×"兜底 —— 对 `gpt-5.5` 会少算 20%（2.0÷2.5），对 `gpt-4.1`（官方 1.75×）、`gpt-4o`（1.7×）会多算；表外模型保持 Standard 并在输出里标"无 Fast 价"。

### 4.3 别名映射（无公开价的两个标签）

| 原始标签 | 建议目标 | 先例 | 输出标注建议 |
|---|---|---|---|
| `codex-auto-review` | 按日志日期映射到"当时最新的已知 GPT-5.x(-codex)"：`2026-04-23`→`gpt-5.5`、`2026-03-05`→`gpt-5.4`、`2026-02-05`→`gpt-5.3-codex`、`2025-12-11`→`gpt-5.2-codex`、`2025-11-13`→`gpt-5.1-codex`、`2025-09-15`→`gpt-5-codex`、`2025-08-07`→`gpt-5` | ccusage 的 `codex-auto-review-fallbacks.json` 🟢 | 保留原始 label + `priced_as` 字段 + `assumed: true`；不要静默改名 |
| `gpt-reserve` | `gpt-5.6-luna`（"Luna Reserve" 的底层模型家族） | agentsview `supplemental.go` 注释 🟢 | 同上；`assumed: true` |

补充建议：别名表**做成数据文件**（可随日期更新、可在 `--schema` 里暴露版本），而不是硬编码在解析逻辑里；映射表要能通过环境变量/配置文件覆盖（ccusage 用 `CCUSAGE_MODEL_ALIASES`，我们可以做得更显式）。

### 4.4 不确定性清单（必须写进文档/输出）

1. 🟡 `gpt-5.3-codex` / `5.2-codex` / `5.1-codex` 的 Fast 价**官方表里没有行**，只有 LiteLLM 的 2.0× —— 用它属于"第三方数据"，建议在定价表里标注来源。
2. 🟡 `gpt-5-codex` 连 LiteLLM priority 都没有 → 若其出现 Fast 轮次，只能保持 Standard 或标 `unknown`。
3. 🟡 `codex-auto-review` 的别名映射是"按日期取最新已知模型"的**猜测**（ccusage 的做法，且其候选正则排除了 5.6 系），真实路由由服务端决定、可能随时间变化（issue #20981 至今未得到官方口径）。
4. 🟡 `gpt-reserve` 映射到 `gpt-5.6-luna` 是**第三方先例**（agentsview），非官方；Reserve 是否另有折扣/额度口径未知。
5. ⬜ 官方 Fast 表与 LiteLLM 快照都是**时间点快照**：官方有促销（"GPT-5.6 Sol's promotional pricing is available at least through November 21, 2026"）与地区 uplift（data residency +10%），按天对账应记录定价表版本日期。
6. ⬜ 本机 `flex` 样本为 0，Flex 行为（0.5×）未在真实日志上验证。
7. ⬜ ccusage 快照的版本号未记录；TS/Rust 两条路径的 Fast 兜底行为不同（2× vs 1×），引用时需注意版本。

---

## 附录 A. 证据索引（全部抓取于 2026-09-21 UTC）

| # | 内容 | URL |
|---|---|---|
| 1 | API Fast mode（原 priority processing）：更名、`priority`≡`fast`、per-token premium、降级回 `default` | <https://platform.openai.com/docs/guides/priority-processing.md> |
| 2 | 官方 Standard / Fast / Flex 逐模型价表、GPT-5.6 Sol Fast = 2×、Astra EU 不可用 | <https://platform.openai.com/docs/pricing.md> |
| 3 | Codex 产品文档 Speed：credits 倍率（5.6/5.5=2.5×、5.4=2×）、Astra 2.5×、API priority 口径、`/fast` 与 config.toml | <https://learn.chatgpt.com/docs/agent-configuration/speed.md> |
| 4 | Codex 产品文档 Pricing：credits/1M tokens 表 | <https://learn.chatgpt.com/docs/pricing.md> |
| 5 | Codex 源码：ServiceTier 枚举/请求值、`default` 哨兵 | <https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/config_types.rs> |
| 6 | Codex 源码：模型目录（`codex-auto-review` 条目、各模型 service_tiers、无价格字段） | <https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json> |
| 7 | Codex 源码：`LUNA_RESERVE_MODEL = "gpt-reserve"` / "Luna Reserve" | <https://raw.githubusercontent.com/openai/codex/main/codex-rs/tui/src/model_catalog.rs> |
| 8 | Codex 源码：Reserve 是耗尽的兜底 | <https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/error.rs> |
| 9 | Codex PR：三种 service tier 状态与 `fast`→`priority` 归一化 | <https://github.com/openai/codex/pull/23537> |
| 10 | Codex issue：`codex-auto-review` 无法映射到官方定价（open） | <https://github.com/openai/codex/issues/20981> |
| 11 | ccusage：Codex 解析器（tier 读取、auto-review fallback） | <https://raw.githubusercontent.com/ccusage/ccusage/main/rust/adapters/codex/src/parser.rs> |
| 12 | ccusage：auto-review 映射快照 | <https://raw.githubusercontent.com/ccusage/ccusage/main/rust/adapters/codex/src/codex-auto-review-fallbacks.json> |
| 13 | ccusage：Fast 倍率 override 表 | <https://raw.githubusercontent.com/ccusage/ccusage/main/rust/crates/ccusage-core/src/fast-multiplier-overrides.json> |
| 14 | ccusage：模型别名只来自环境变量 | <https://raw.githubusercontent.com/ccusage/ccusage/main/rust/crates/ccusage-core/src/model_aliases.rs> |
| 15 | ccusage：Codex 定价文档（"experimental"、`--speed auto`） | <https://github.com/ccusage/ccusage/blob/main/docs/guide/codex/index.md> |
| 16 | ccusage PR #996：TS 侧 fast 倍率与 2× 兜底 | <https://github.com/ccusage/ccusage/pull/996/files> |
| 17 | agentsview：`gpt-reserve` → `gpt-5.6-luna` 定价先例 | <https://raw.githubusercontent.com/kenn-io/agentsview/main/internal/pricing/supplemental.go> |
| 18 | models.dev api.json（无 priority/flex） | <https://models.dev/api.json> |
| 19 | LiteLLM 价目表上游（快照最后提交 `b1a61f510c90` @ 2026-09-13T04:13:52Z） | <https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json> |

本机素材（只读引用，未修改）：

- `.scratch/litellm.json`、`.scratch/models.dev.json`（2026-09-21 19:07 保存的快照）
- `.scratch/ccusage.json`（本机 ccusage 输出快照，含 2026-09-11/12/13 三天）
- `~/.codex/sessions/2026/09/{10,11,12,13}/*.jsonl`（132 个文件；`~/.codex/config.toml` 只读）

## 附录 B. 本机复算口径与命令

复算脚本为一次性只读扫描（不落盘、不改仓库），口径如下：

- `turn_context.payload.model` → 当前模型；`event_msg.payload.type=="thread_settings_applied"` 的 `thread_settings.service_tier` → 当前档位；`event_msg.payload.type=="token_count"` 的 `info.last_token_usage` 计一轮。
- 净输入 = `input_tokens − cached_input_tokens`；缓存读 = `cached_input_tokens`；输出 = `output_tokens`。
- 归日：事件时间戳 UTC + 8 小时（本机时区）。
- 2026-09-12 各档 token（用于 2.6 的反推）：priority — `gpt-6-astra` 725,373 / 38,867,968 / 120,880，`gpt-5.6-luna` 193,807 / 3,323,392 / 14,275，`codex-auto-review` 195,046 / 1,744,384 / 6,683。
