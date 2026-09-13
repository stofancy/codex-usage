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

## 5. 同步（公开渠道 → 用户缓存）

```python
from codex_usage import pricing

pricing.sync("models.dev")            # → {"path": "~/.cache/codex-usage/pricing.json",
                                      #    "models": 2086, "source": "models.dev"}
pricing.sync("litellm", timeout=30.0)
```

- 原子写（临时文件 + `os.replace`），失败抛异常且**不会**留下半截缓存。
- CLI 里由 `codex-usage --update-pricing [--pricing-source litellm]` 调用并捕获异常。
- 缓存目录可用 `CODEX_USAGE_CACHE_DIR` 覆盖（测试与容器场景）。

## 6. 与 cc-switch 的关系

cc-switch 的 `~/.cc-switch/model-pricing.json` 仍是**最高优先级的覆盖层**：用户已有该文件时，
它的每一条同名定价都会覆盖内置表；内置表继续提供它没有的公开模型（这正是避免“旧 cc-switch
文件让新模型全部无价”的关键）。`sync` 写出的用户缓存格式与 cc-switch 兼容，可双向复制。

## 7. 已知局限

- **转售商价格差异**：同一个模型在不同 provider/中转站价格不同。内置表按权威度取一条，
  不能反映用户实际走的渠道加价；需要精确账单请把自己的 cc-switch 表放进
  `CODEX_USAGE_PRICING_FILE`（同名项会覆盖内置价）。
- **未计价格档位**：渠道的 context 阶梯价（`tiers` / `context_over_200k`）、
  `cache_write`（缓存写）、priority/flex 档均未纳入，成本按首档基础价估算。
- **快照时效**：内置表是生成时点的快照（见文件里的 `updated`），新模型可能缺价；
  无定价的模型 token 照常统计、成本显示 `$0.00*` 并在表尾提示。
- **公开渠道没有的名字才不会算价**：内置表只来自 models.dev / LiteLLM 的公开数据；
  本机出现过但公开渠道未收录的模型名（例如某些内部中转或自建别名）保持 `$0.00*`，
  可按需写进自己的 `CODEX_USAGE_PRICING_FILE` 覆盖层。
