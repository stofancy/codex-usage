# 模型定价（Pricing）

`codex-usage` 的成本列来自本地定价表。为了让开源用户**开箱即用**（没有
`~/.cc-switch/model-pricing.json` 也能看到成本），仓库内置了一份公开定价快照，
并提供一条免认证渠道的同步命令。

## 1. 数据源

| 渠道 | URL | 认证 | 原始单位 | 许可 / 署名 |
| --- | --- | --- | --- | --- |
| **models.dev**（内置表来源，默认） | `https://models.dev/api.json` | 免认证 | `$/M tokens` | MIT · <https://github.com/sst/models.dev> |
| **LiteLLM**（备选） | `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | 免认证 | `$/token`（×1e6） | MIT · <https://github.com/BerriAI/litellm> |

字段映射：

```
models.dev   provider.models[id].cost.input       → inputCostPerMillion        ($/M)
             provider.models[id].cost.output      → outputCostPerMillion       ($/M)
             provider.models[id].cost.cache_read  → cacheReadCostPerMillion    ($/M)
             provider.models[id].cost.cache_write → （无对应字段，见“已知局限”）

LiteLLM      input_cost_per_token                 → inputCostPerMillion        ($/M = $/token × 1e6)
             output_cost_per_token                → outputCostPerMillion       ($/M)
             cache_read_input_token_cost          → cacheReadCostPerMillion    ($/M)
```

## 2. 内置表

- 路径：`src/codex_usage/data/pricing.json`（随包分发，`importlib.resources` 读取，无网络也能用）。
- 格式：**cc-switch 兼容**

```json
{
  "source": "models.dev",
  "updated": "2026-09-13T11:16:39+00:00",
  "models": [
    {"modelId": "gpt-5.1-codex", "inputCostPerMillion": 1.25,
     "cacheReadCostPerMillion": 0.125, "outputCostPerMillion": 10.0}
  ]
}
```

- 收录范围：约 2000 个有公开定价的模型（OpenAI / Anthropic / Codex 变体系列、
  Google、DeepSeek、xAI、Moonshot、GLM 等）。
- 收录规则（`records_from_modelsdev` / `records_from_litellm`）：
  1. 只收 `input`/`output` 齐全且**非全 0**的条目（全 0 视为“未定价”，不冒充免费）；
  2. 过滤非文本生成模型（embedding / image / audio / tts / rerank 等，按模型名与
     `modalities.output` 判断）；
  3. 剥掉渠道 model id 的 provider 前缀（`openrouter/openai/gpt-5.1-codex` →
     `gpt-5.1-codex`）；
  4. 同名模型按 **provider 权威度**去重：模型作者官方 > 原价镜像/网关
     （helicone / llmgateway / openrouter / vercel…）> 云托管（azure / bedrock / vertex…）
     > 其余按 provider id 排序。避免转售商低价或缺少缓存价的条目覆盖官方价。
  5. **只收公开渠道里真实存在的模型**：生成器只读渠道 JSON，不读本机任何定价文件，
     所以本机出现过、公开渠道没有收录的模型（例如某些内部中转名）天然不会入表，
     其成本显示 `$0.00*`。早期版本曾用硬编码黑名单排除个别名字，现已移除——
     只要公开渠道有价（例如 `gpt-6-astra` 在多家 provider 有 10/50 的报价）就应当收录。
- 生成 / 更新（维护者，构建期）：

```bash
# 真实拉取 models.dev 并刷新内置表（默认输出上面那个路径）
python tools/sync_pricing.py

# 备选渠道 / 指定输出 / 离线用本地快照重建（CI 与测试都不联网）
python tools/sync_pricing.py --source litellm --out /tmp/pricing.json
python tools/sync_pricing.py --source models.dev --input .scratch/models.dev.json

# 只统计不落盘；或保留渠道原始 JSON 供对比
python tools/sync_pricing.py --dry-run
python tools/sync_pricing.py --format raw --out /tmp/models.dev.json
```

## 3. 合并加载

`load_pricing()`（无参）把三层**合并**，同名 `modelId` 由更高优先级的层覆盖（内置表是基底）：

| 层 | 来源 | 角色 |
| --- | --- | --- |
| 低 | 包内置表 `src/codex_usage/data/pricing.json` | 基底：公开模型的完整覆盖 |
| 中 | 用户缓存 `~/.cache/codex-usage/pricing.json`（`CODEX_USAGE_CACHE_DIR` 可覆盖） | `--update-pricing` / `sync` 写入 |
| 高 | `CODEX_USAGE_PRICING_FILE`（未设置时 `~/.cc-switch/model-pricing.json`） | 用户私有定价，覆盖同名项 |

因此：用户既保留自己的私有/自定义定价，又能拿到内置表的完整公开覆盖（不会因为一个
过时的 cc-switch 文件而丢掉新模型）。**任一层缺失 / 为空 / JSON 损坏都只跳过该层**，
不影响其余层；三层都不可用时返回空表（成本按 `$0` 计并标注 `*`），不会抛异常。

显式传入 `path` 时（如 `load_pricing(path)`）**严格只读该文件**，不回退不合并——
`--doctor` 用它判断“用户指定文件是否存在”。

`source_info()` 返回合并结果：

```python
{"source": "builtin+user-cache+env-file",   # 生效的层，低→高优先级
 "path": "/…/model-pricing.json",           # 最高优先级层路径（用户层优先，否则内置表）
 "models": 2090,                            # 合并后真实条数（不含归一化别名）
 "updated": "2026-09-13T11:22:29+00:00",    # 各层里最新的 updated
 "layers": [{"source": "builtin", "path": "…/data/pricing.json", "models": 2086,
             "updated": "…"}, {"source": "env-file", "path": "/…/model-pricing.json",
             "models": 56, "updated": None}]}
```

判断某层是否生效：`"env-file" in info["source"]`，或遍历 `info["layers"]`。

## 4. 模型名匹配

会话里的模型名常带日期或渠道前缀，`model_cost()` / `lookup()` 按三档匹配：

1. **精确**：`pricing[model]`
2. **归一化**（`normalize_model()`）：小写、剥 provider 前缀、剥 `-latest/-preview`、
   剥日期后缀（`-2025-11-13` / `-20251113`）、常见别名（`claude-3.5-sonnet` →
   `claude-3-5-sonnet`）。例：`GPT-5.1-Codex` → `gpt-5.1-codex`；
   `gpt-5.1-codex-2025-11-13` → `gpt-5.1-codex`。
3. **前缀**：表中最长的、以 `-` 分段的 key 是模型名前缀时命中，用于中转变体
   （`gpt-5.6-sol-yytoken` → `gpt-5.6-sol`）。为避免误配，只有**至少两段且长度 ≥4**
   的 key 才参与前缀匹配（`gpt` / `o3` 这类过泛 key 不参与）。

## 5. cache_read 价缺失时的回退（保守上界）

公开渠道对部分模型只登记 input/output 价，没有 cache read 价（`cost.cache_read` 缺失）。
旧口径把这类模型的缓存读按 **$0/M** 计，会系统性低估成本；现在改为：

| 情况 | 缓存读用的价格 |
| --- | --- |
| 表里有 cache read 价且 > 0 | 该 cache read 价（行为不变） |
| 表里**没有** cache read 价 | **回退用该模型的 input 价** |
| 表里 cache read 价**显式为 0** | **回退用该模型的 input 价**（0 视为“未登记”，不是“免费”） |
| 记录缺 input 价（缺失 / `null` / 负数） | 整行视为无定价 → 成本 `$0.00*` |

**为什么回退到 input 价（上界）而不是 $0**：真实 cache read 价通常只有 input 价的
~10%（如 `gpt-5.6-sol`：input 4 / cache_read 0.4），按 input 计只会**多算、不会少算**；
按 $0 计则一定少算。诊断口径与 ccusage 的「cached input 用 cache-read 价、缺失时回退
input 价」一致，便于对账。代价是这类模型成本偏高，需要精确值请在自己的
`CODEX_USAGE_PRICING_FILE` 里补 `cacheReadCostPerMillion`。

**怎么看出“这一行用了回退”**：`model_cost()` 的返回保持不变，新增明细接口

```python
from codex_usage import pricing

detail = pricing.model_cost_detail(pricing.load_pricing(), "gpt-5-pro", 1_000_000, 1_000_000, 0)
# {"model": "gpt-5-pro", "matched": "gpt-5-pro", "cost_usd": 30.0,
#  "fallbacks": ["cacheReadCostPerMillion"]}     ← 空列表 = 完全按表内价格
```

`fallbacks` 只会在该行**价格层面**发生回退时非空（即使该行 cache read tokens 为 0，
也会标记，便于诊断；此时不影响金额）。未命中定价返回 `None`。

**覆盖缺口量级（2026-09-13 快照）**：内置表 2086 条中 **717 条（34.4%）**没有 cache
read 价；叠加用户层后的生效合并表 2329 条中 **783 条（33.6%）**。典型缺口是官方只给
input/output 的推理档：`gpt-5-pro`、`gpt-5.2-pro`、`gpt-5.5-pro`、`o1-pro`、
`gpt-4-turbo`、`gpt-4o-2024-05-13`。

**实测影响**：本机 `--since 20260911` 的 126 个会话，旧口径 **$1,062.11** → 新口径
**$1,062.11**，增量 **$0.00（0.000%）**——该批数据用到的模型（`gpt-5.6-sol/luna/terra`、
`gpt-6-astra`、`deepseek-v4-*` 等）都有 cache read 价，所以回退只在用到 pro 系列等
缺价模型时才会体现。

## 6. 档位（priority / Fast / Flex）定价

Codex 的 `thread_settings_applied.service_tier` 会标注本轮用量走的档位（parser 归到
`Session.tiers[model][tier]`）。计价规则：

| 档位值 | 归一后 | 用的价格 |
| --- | --- | --- |
| `priority`、`fast` | `priority` | Fast 档价（官方 2026-07-30 把 priority processing 改名为 Fast，**同一档**） |
| `flex` | `flex` | Flex 档价（官方 = 标准价 0.5×） |
| `default`、`standard` | `standard` | 标准价（行为不变） |
| `unknown`（整个会话没有 settings 事件） | 由 `~/.codex/config.toml` 的 `service_tier` 决定（读不到 = `default` = 标准价） | 同左 |
| 其它未知值 | `standard` | 标准价 |

**价格来源**：`src/codex_usage/data/tier_pricing.json`（`CODEX_USAGE_TIER_PRICING_FILE`
可覆盖），生成自 LiteLLM 快照 `model_prices_and_context_window.json @ b1a61f510c90`
（2026-09-13T04:13:52Z），逐模型收录 `*_priority` / `*_flex` 价。与 OpenAI 官方
[Fast/Flex 价目表](https://platform.openai.com/docs/pricing.md)（抓取 2026-09-21）逐项一致：
Astra / 5.6 Sol·Terra·Luna / 5.4 / 5.4-mini = **2.0×**，**gpt-5.5 = 2.5×**（官方例外），
Flex = 0.5×。官方 Fast 表**没有** 5.1/5.2/5.3-codex 的行，只有 LiteLLM 的 2.0×，因此这些
条目标 `confidence: litellm`（低置信，默认启用）；`gpt-5-codex` 连 priority 价都没有 →
出现 Fast 轮次时保持标准价并标 `tier_priced: false`。**不做“统一 2×”兜底**：那会在 5.5 上
少算 20%、在 gpt-4.1/4o 上多算。

> **口径声明**：本仓库按 **API 等价美元**计价（Astra 2×、5.6 系 2×、5.5 2.5×、5.4 2×）。
> ChatGPT 订阅的 credits 口径是另一套倍率（5.6/5.5 = 2.5×、Astra = 2.5×），两者不同，
> 不混用。

```python
from codex_usage import pricing

table = pricing.load_pricing()
pricing.model_cost(table, "gpt-5.6-sol", net_in, cached, out, tier="priority")  # Fast 价
pricing.model_cost_detail(table, "gpt-5.6-sol", net_in, cached, out, tier="fast")
# {"tier": "priority", "tier_priced": True, "tier_confidence": "official",
#  "cost_usd": ..., "standard_cost_usd": ...}
pricing.cost_for_tiered(session.tiers, table)   # 按 Session.tiers 分档汇总
pricing.tier_multiplier(table, "gpt-5.5", "priority")   # → 2.5
```

**实测覆盖（本机 09-11 起）**：`default` 1,465,877,341 tokens、`unknown` 435,456,096、
`priority` 44,376,939（priority 约占 2.3% tokens、9.5% 成本）。priority 加成 **+$54.59**，
其中 `gpt-6-astra` +$51.40、`codex-auto-review`→`gpt-5.5` +$3.07、`gpt-5.6-luna` +$0.12。

## 7. 别名映射（无可信价的标签）

`src/codex_usage/data/model_aliases.json`（`CODEX_USAGE_ALIASES_FILE` 可覆盖，带 `version`）
只收录**有依据的假设映射**，命中时明细里保留原始标签并给出 `priced_as` + `assumed: true`：

| 原始标签 | 映射到 | 依据（抓取 2026-09-21） | 不确定性 |
| --- | --- | --- | --- |
| `codex-auto-review` | `gpt-5.5` | [ccusage 的 auto-review fallback 表](https://raw.githubusercontent.com/ccusage/ccusage/main/rust/adapters/codex/src/codex-auto-review-fallbacks.json)（按发布日取当时最新 gpt-5.x，2026-09-12 日志 → gpt-5.5）+ 本机三方对账：ccusage 输出的 `gpt-5.5` 行 `isFallback: true`，token 与本机 `codex-auto-review` 一致 | **假设**：Codex 目录里该 slug 无任何价格字段，官方 issue [#20981](https://github.com/openai/codex/issues/20981) 至今 open；路由由服务端决定，可能随时间变化 |
| `gpt-reserve` | **不映射** | Luna Reserve（额度耗尽兜底），OpenAI/LiteLLM/models.dev 均无价，ccusage 也计 $0 | agentsview 把它映射到 `gpt-5.6-luna` 是**另一个工具的选择**，本项目不臆造 → 保持 `$0.00*` |
| `gpt-5-codex` | **不映射** | 官方 Fast 表无行、LiteLLM 也无 priority 价 | Fast 轮次保持标准价并标 `tier_priced: false` |

优先级：**定价表里的真实同名记录 > 别名映射**（用户在 `CODEX_USAGE_PRICING_FILE` 里显式
写了 `codex-auto-review` 的价就以用户的为准）。别名目标本身无价时**仍返回 `None`（标 `*`）**，
不会静默算出一个价。映射表损坏/缺失时安全退回精确/归一化/前缀匹配。

## 8. 同步（公开渠道 → 用户缓存）

```python
from codex_usage import pricing

pricing.sync("models.dev")            # → {"path": "~/.cache/codex-usage/pricing.json",
                                      #    "models": 2086, "source": "models.dev"}
pricing.sync("litellm", timeout=30.0)
```

- 原子写（临时文件 + `os.replace`），失败抛异常且**不会**留下半截缓存。
- CLI 里由 `codex-usage --update-pricing [--pricing-source litellm]` 调用并捕获异常。
- 缓存目录可用 `CODEX_USAGE_CACHE_DIR` 覆盖（测试与容器场景）。

## 9. 与 cc-switch 的关系

cc-switch 的 `~/.cc-switch/model-pricing.json` 仍是**最高优先级的覆盖层**：用户已有该文件时，
它的每一条同名定价都会覆盖内置表；内置表继续提供它没有的公开模型（这正是避免“旧 cc-switch
文件让新模型全部无价”的关键）。`sync` 写出的用户缓存格式与 cc-switch 兼容，可双向复制。

## 10. 已知局限

- **转售商价格差异**：同一个模型在不同 provider/中转站价格不同。内置表按权威度取一条，
  不能反映用户实际走的渠道加价；需要精确账单请把自己的 cc-switch 表放进
  `CODEX_USAGE_PRICING_FILE`（同名项会覆盖内置价）。
- **未计价格档位**：渠道的 context 阶梯价（`tiers` / `context_over_200k`，注意这个
  `tiers` 是上下文分档，与 service tier 无关）与 `cache_write`（缓存写）仍未纳入，
  成本按首档基础价估算；priority/Fast/Flex 见第 6 节。
- **cache read 回退是上界**：缺 cache read 价的模型按 input 价计（见第 5 节），会高估
  这些模型的成本；这是“宁多算不少算”的取舍，精确值可在自己的定价表里补。
- **档位覆盖率与归因缺口**：实测 09-11 起仍有 435.5M tokens 落在 `unknown`（按
  `config.toml` 的 `service_tier` 兜底），另发现 1 个 session/model 的 `tiers` 逐档合计
  比 `models` 少 4.81M 毛输入（parser 侧归因缺口），分档计价会少算这部分（≈$5.4）。
- **快照时效**：内置表与档位价表都是生成时点的快照（见各自 `updated`），新模型/新倍率
  可能缺；无定价的模型 token 照常统计、成本显示 `$0.00*` 并在表尾提示。
- **公开渠道没有的名字才不会算价**：内置表只来自 models.dev / LiteLLM 的公开数据；
  本机出现过但公开渠道未收录、且别名表未映射的名字（如 `gpt-reserve`）保持 `$0.00*`，
  可按需写进自己的 `CODEX_USAGE_PRICING_FILE` 覆盖层。
