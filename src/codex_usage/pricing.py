"""模型定价：内置公开定价表 + 免认证渠道同步 + cc-switch 兼容加载。

加载语义（``load_pricing``）：
- ``load_pricing()``（无参）**合并**三层，同名 modelId 后写覆盖：::

      内置表（基底，随包发行） ← 用户缓存 ``~/.cache/codex-usage/pricing.json``
                              ← ``CODEX_USAGE_PRICING_FILE`` / ``~/.cc-switch/model-pricing.json``

  用户既能保留私有定价（覆盖同名项），又能拿到公开模型的完整覆盖。
- ``load_pricing(path)``：严格只读该文件（doctor 用它判断“指定文件是否存在”），不回退/不合并。

任一层的文件缺失、为空或 JSON 损坏都只跳过该层，不影响其余层，也绝不抛异常；
三层都不可用时返回空表（成本按 $0 计并由调用方标注 ``*``）。公开用户没有
``~/.cc-switch/model-pricing.json`` 时也能直接看到成本。

公开渠道（免认证）：
    models.dev  https://models.dev/api.json                                （$/M tokens）
    LiteLLM     .../model_prices_and_context_window.json                    （$/token，×1e6）
"""

import json
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache

from . import config

# ---------------------------------------------------------------- 公开渠道

SOURCES: dict[str, dict[str, str]] = {
    "models.dev": {
        "url": "https://models.dev/api.json",
        "format": "models-dev",
        "license": "MIT (https://github.com/sst/models.dev)",
    },
    "litellm": {
        "url": "https://raw.githubusercontent.com/BerriAI/litellm/main/"
               "model_prices_and_context_window.json",
        "format": "litellm",
        "license": "MIT (https://github.com/BerriAI/litellm)",
    },
}
DEFAULT_SOURCE = "models.dev"

#: 生成内置表时的 provider 权威度排序：模型作者官方 > 原价镜像/网关 > 云托管 > 其余按 provider id 排序。
#: 同名模型只保留排序最靠前的价格（避免转售商低价或缺少缓存价的条目覆盖官方价）。
PROVIDER_PRIORITY: list[str] = [
    # 模型作者 / 官方 API
    "openai", "anthropic", "google", "deepseek", "xai", "mistral", "meta",
    "moonshotai", "moonshotai-cn", "zai", "zhipuai", "minimax", "minimax-cn",
    "stepfun", "stepfun-ai", "longcat", "inception", "upstage",
    # 原价镜像 / 路由网关（记录模型原价，含缓存价）
    "helicone", "llmgateway", "llmgateway-providers", "openrouter", "vercel",
    "requesty", "opencode", "kilo",
    # 云托管 / 推理平台
    "azure", "azure-cognitive-services", "amazon-bedrock",
    "google-vertex", "google-vertex-anthropic",
    "alibaba", "alibaba-cn", "volcengine", "siliconflow", "siliconflow-cn",
    "groq", "cerebras", "cohere", "perplexity", "togetherai", "fireworks-ai",
    "deepinfra", "nvidia", "novita-ai", "nebius", "baseten", "huggingface",
    "cloudflare-workers-ai", "cloudflare-ai-gateway", "ollama-cloud", "lmstudio",
    "databricks", "snowflake-cortex", "sap-ai-core", "watsonx", "wandb",
    # 其余聚合站 / 转售商
    "github-copilot", "poe", "nano-gpt", "aihubmix", "zenmux", "abacus",
    "fastrouter", "orcarouter", "edenai", "aiand",
]
_PRIORITY_INDEX = {pid: i for i, pid in enumerate(PROVIDER_PRIORITY)}

#: 非文本生成模型（图像/语音/向量等）不进内置表：它们不产生 token 成本口径。
_NON_TEXT_RE = re.compile(
    r"(?:^|[-_/.])("
    r"embeddings?|rerank\w*|moderation|images?|dall[-_]?e|stable-diffusion|nova-canvas|"
    r"sora|veo|flux|seedream|kling|midjourney|recraft|ideogram|whisper|transcri\w*|"
    r"speech|tts|audio|voice|music|lyria|ocr|colpali|clip|bge"
    r")(?:$|[-_/.])"
)
#: LiteLLM 的 mode 字段里属于非文本生成的取值。
_NON_TEXT_MODES = ("embedding", "image", "audio", "speech", "transcription",
                   "moderation", "rerank", "video", "ocr")

# ------------------------------------------------ 模型名归一化与匹配

_PROVIDER_PREFIX_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]*/")
#: 版本日期后缀：2025-11-13 / 20251113（分隔符可混用）
_DATE_SUFFIX_RE = re.compile(r"[-_.](?:20\d{2})[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])$")
_LATEST_SUFFIX_RE = re.compile(r"[-_.](?:latest|preview|stable)$")

# ---- 档位（service tier）与别名映射 ------------------------------------------

TIER_STANDARD = "standard"
TIER_PRIORITY = "priority"
TIER_FLEX = "flex"
#: 官方 2026-07-30 把 priority processing 改名为 Fast：`fast` 与 `priority` 同档。
_TIER_ALIASES = {"fast": TIER_PRIORITY, "priority": TIER_PRIORITY, "flex": TIER_FLEX,
                 "default": TIER_STANDARD, "standard": TIER_STANDARD, "": TIER_STANDARD}
#: 档位数据里标为 official 的模型（OpenAI 官方 Fast/Flex 价目表有独立行）。
OFFICIAL_TIER_MODELS = frozenset({
    "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.2", "gpt-5.1", "gpt-5",
})
#: 数据文件覆盖用的环境变量（未设置时读包内 data/ 资源）。
ALIASES_FILE_ENV = "CODEX_USAGE_ALIASES_FILE"
TIER_PRICING_FILE_ENV = "CODEX_USAGE_TIER_PRICING_FILE"
CODEX_CONFIG_ENV = "CODEX_USAGE_CODEX_CONFIG"
#: 少量常见别名（归一化后仍需纠正的写法）。
_ALIASES = {
    "claude-3.5-sonnet": "claude-3-5-sonnet",
    "claude-3.7-sonnet": "claude-3-7-sonnet",
    "claude-3.5-haiku": "claude-3-5-haiku",
    "gpt-5.1-codex-latest": "gpt-5.1-codex",
    "gpt-5-codex-latest": "gpt-5-codex",
}


@lru_cache(maxsize=8192)
def normalize_model(name: str) -> str:
    """归一化模型名用于宽松匹配：去大小写、provider 前缀、日期/``-latest`` 后缀、别名。

    ``gpt-5.1-codex-2025-11-13`` → ``gpt-5.1-codex``；
    ``openrouter/openai/GPT-5.1-Codex`` → ``gpt-5.1-codex``；``codex-mini-latest`` → ``codex-mini``。
    """
    s = (name or "").strip().lower()
    if not s:
        return ""
    for _ in range(3):                      # 最多剥 3 段 provider 前缀（openrouter/openai/...）
        stripped = _PROVIDER_PREFIX_RE.sub("", s)
        if stripped == s:
            break
        s = stripped
    prev = None
    while s and s != prev:                  # 反复剥日期后缀（同时存在年份与完整日期时）
        prev = s
        s = _DATE_SUFFIX_RE.sub("", s)
    s = _LATEST_SUFFIX_RE.sub("", s)
    return _ALIASES.get(s, s)


def _prefix_lookup(pricing: dict, normalized: str) -> str | None:
    """在表中找最长的“表 key 是模型名前缀”匹配（``gpt-5.6-sol-yytoken`` → ``gpt-5.6-sol``）。

    只接受至少两段（含 ``-``）且长度 ≥4 的 key，避免 ``gpt`` 这类过泛条目把
    本机出现但公开渠道未收录的模型名误算成某个通用模型的价。
    """
    best, best_len = None, 0
    for key in pricing:
        nk = normalize_model(key)
        if ("-" not in nk or len(nk) < 4 or len(nk) <= best_len
                or not normalized.startswith(nk + "-")):
            continue
        best, best_len = key, len(nk)
    return best


def _lookup_direct(pricing: dict, name: str) -> tuple[str, dict] | None:
    """精确 → 归一化 → 前缀（不查别名映射，避免映射链成环）。"""
    hit = pricing.get(name)
    if hit is not None:
        return name, hit
    n = normalize_model(name)
    if not n:
        return None
    hit = pricing.get(n)
    if hit is not None:
        return n, hit
    key = _prefix_lookup(pricing, n)
    return (key, pricing[key]) if key else None


def _alias_spec(model: str, normalized: str | None) -> dict | None:
    """查别名映射规则（原始名优先，其次归一化名）；无规则/表为空返回 None。"""
    aliases = load_aliases()
    if not aliases:
        return None
    return aliases.get(model.strip().lower()) or (aliases.get(normalized) if normalized else None)


def _lookup_hit(pricing: dict[str, dict], model: str) -> tuple[str, dict, dict | None] | None:
    """按 精确 → 归一化 → **别名映射** → 前缀 查找 → (表 key, 价格记录, 别名规则|None)。

    表内**真实**的 ``codex-auto-review`` 记录优先；``_with_aliases`` 注入的映射副本带
    ``_alias_of`` 标记，会转成别名路径，从而保留 ``priced_as`` / ``assumed`` 与档位映射。
    """
    if not pricing or not model:
        return None
    n = normalize_model(model)
    spec = _alias_spec(model, n)

    def via_alias(target: str):
        thit = _lookup_direct(pricing, target)
        if thit is None:
            return None
        return thit[0], thit[1], spec or {"model": target, "assumed": True}

    hit = pricing.get(model)
    if hit is not None:
        injected = hit.get("_alias_of") if isinstance(hit, dict) else None
        if injected and spec:
            return via_alias(str(injected)) or (model, hit, None)
        return model, hit, None
    if n:
        hit = pricing.get(n)
        if hit is not None:
            injected = hit.get("_alias_of") if isinstance(hit, dict) else None
            if injected and spec:
                return via_alias(str(injected)) or (n, hit, None)
            return n, hit, None
    if spec:
        got = via_alias(str(spec.get("model") or ""))
        if got is not None:
            return got
    if not n:
        return None
    key = _prefix_lookup(pricing, n)
    return (key, pricing[key], None) if key else None


def lookup(pricing: dict[str, dict], model: str) -> dict | None:
    """按 精确 → 归一化 → 别名映射 → 前缀 查找价格记录；找不到返回 None。"""
    hit = _lookup_hit(pricing, model)
    return hit[1] if hit else None


# ---------------------------------------------------------------- 文件读取


def _builtin_traversable():
    """内置表资源（importlib.resources，兼容 zip 安装）。"""
    from importlib.resources import files
    return files("codex_usage").joinpath("data", "pricing.json")


def builtin_path() -> str:
    """内置表的展示路径（资源解析失败时退回源码目录）。"""
    try:
        return str(_builtin_traversable())
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pricing.json")


def _table_from_payload(raw) -> dict[str, dict]:
    """把 cc-switch 兼容载荷解析成 {modelId: 记录}；结构不识别返回空表。"""
    rows = None
    if isinstance(raw, dict) and isinstance(raw.get("models"), list):
        rows = raw["models"]
    elif isinstance(raw, dict) and isinstance(raw.get("models"), dict):
        rows = [dict(v, modelId=v.get("modelId", k)) for k, v in raw["models"].items()
                if isinstance(v, dict)]
    elif isinstance(raw, dict):
        # 裸 {modelId: {成本字段}}；要求至少一条带已知成本字段，避免误吃渠道原始格式
        values = [v for v in raw.values() if isinstance(v, dict)]
        if values and any(("inputCostPerMillion" in v or "outputCostPerMillion" in v)
                          for v in values):
            rows = [dict(v, modelId=v.get("modelId", k)) for k, v in raw.items()
                    if isinstance(v, dict)]
    if not rows:
        return {}
    table: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("modelId") or row.get("id")
        if mid:
            table[str(mid)] = row
    return table


def _read_pricing(path: str, *, builtin: bool = False) -> tuple[dict[str, dict], dict]:
    """读一层定价表 → (表, 元数据)；缺失/损坏/为空都返回空表而不抛异常。"""
    meta: dict = {"path": path, "models": 0, "updated": None}
    try:
        if builtin:
            text = _builtin_traversable().read_text(encoding="utf-8")
        else:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        raw = json.loads(text)
        table = _table_from_payload(raw)
        if not table:
            return {}, meta
        meta["models"] = len(table)
        if isinstance(raw, dict):
            stamp = raw.get("updated") or raw.get("updatedAt")
            if isinstance(stamp, str) and stamp.strip():
                meta["updated"] = stamp.strip()
        if not meta["updated"] and not builtin:
            try:
                meta["updated"] = datetime.fromtimestamp(
                    os.path.getmtime(path), tz=timezone.utc).isoformat(timespec="seconds")
            except OSError:
                pass
        return table, meta
    except Exception:
        return {}, meta


def _data_traversable(filename: str):
    """包内 data/ 资源（importlib.resources，兼容 zip 安装）。"""
    from importlib.resources import files
    # 分两次 joinpath：Traversable.joinpath 的类型存根只接受单个参数，多参形式 mypy 报 call-arg。
    return files("codex_usage").joinpath("data").joinpath(filename)


def _read_data_file(filename: str, env_var: str):
    """读 data/ 下的 JSON（env_var 可覆盖路径）；缺失/损坏返回 None，绝不抛异常。"""
    path = os.environ.get(env_var)
    try:
        if path:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return json.loads(_data_traversable(filename).read_text(encoding="utf-8"))
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, dict]:
    """别名映射表 ``data/model_aliases.json``（``CODEX_USAGE_ALIASES_FILE`` 可覆盖）。

    形如 ``{"codex-auto-review": {"model": "gpt-5.5", "assumed": true, "note": ...}}``；
    文件缺失/损坏/结构不识别时返回空表（安全回退，不影响精确/归一化/前缀匹配）。
    """
    raw = _read_data_file("model_aliases.json", ALIASES_FILE_ENV)
    table = raw.get("aliases") if isinstance(raw, dict) else None
    if not isinstance(table, dict):
        table = raw if isinstance(raw, dict) else {}
    out: dict[str, dict] = {}
    for src, spec in table.items():
        if not isinstance(src, str):
            continue
        if isinstance(spec, str):
            out[src.lower()] = {"model": spec, "assumed": True}
        elif isinstance(spec, dict) and spec.get("model"):
            out[src.lower()] = dict(spec)
    return out


def aliases_info() -> dict:
    """别名表元信息（供 ``--schema``/doctor 展示版本与依据）。"""
    raw = _read_data_file("model_aliases.json", ALIASES_FILE_ENV)
    if not isinstance(raw, dict):
        return {"version": None, "aliases": {}, "not_mapped": {}}
    table = raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {}
    return {"version": raw.get("version"), "updated": raw.get("updated"),
            "aliases": table, "not_mapped": raw.get("not_mapped") or {}}


@lru_cache(maxsize=1)
def load_tier_pricing() -> dict:
    """档位价表 ``data/tier_pricing.json``（``CODEX_USAGE_TIER_PRICING_FILE`` 可覆盖）。

    返回 ``{"priority": {modelId: 记录}, "flex": {...}, "multipliers": {modelId: float},
    "updated": ..., "source": ...}``；文件缺失/损坏时各表为空（一切按标准价）。
    """
    raw = _read_data_file("tier_pricing.json", TIER_PRICING_FILE_ENV)
    out: dict = {"priority": {}, "flex": {}, "multipliers": {}, "updated": None, "source": None}
    if not isinstance(raw, dict):
        return out
    for tier in ("priority", "flex"):
        rows = raw.get(tier)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("modelId"):
                    out[tier][str(row["modelId"]).lower()] = row
    mult = raw.get("multipliers")
    if isinstance(mult, dict):
        out["multipliers"] = {str(k).lower(): float(v) for k, v in mult.items()
                              if isinstance(v, (int, float)) and not isinstance(v, bool)}
    out["updated"] = raw.get("updated")
    out["source"] = raw.get("source")
    return out


def _parse_service_tier(text: str) -> str | None:
    """从 config.toml 文本里取顶层 ``service_tier``（优先 tomllib，回退正则）。"""
    try:
        import tomllib                                  # Python ≥3.11
        value = tomllib.loads(text).get("service_tier")
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    match = re.search(r'^\s*service_tier\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return match.group(1).strip() if match else None


@lru_cache(maxsize=1)
def default_service_tier() -> str:
    """``~/.codex/config.toml`` 的 ``service_tier``（``CODEX_USAGE_CODEX_CONFIG`` 可覆盖）。

    ``Session.tiers`` 里的 ``unknown`` 档用它兜底；读不到/损坏返回 ``"default"``（标准价）。
    进程内缓存一次（改配置后重启进程生效）。
    """
    path = os.environ.get(CODEX_CONFIG_ENV) or os.path.join(
        os.path.expanduser("~"), ".codex", "config.toml")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "default"
    value = _parse_service_tier(text)
    return value or "default"


def resolve_tier(tier: str | None, *, config_tier: str | None = None) -> str:
    """档位归一 → ``standard`` | ``priority`` | ``flex``。

    ``fast``/``priority`` → priority（官方改名同档）；``flex`` → flex；
    ``default``/``standard`` → standard；``None``/``unknown``/空 → ``config_tier``，
    再退回 ``~/.codex/config.toml`` 的 service_tier（本机 default）；其它未知值 → standard。
    """
    raw = (tier or "").strip().lower()
    if raw in ("", "unknown", "none"):
        raw = (config_tier or "").strip().lower() or default_service_tier().strip().lower()
    return _TIER_ALIASES.get(raw, TIER_STANDARD)


def _with_aliases(table: dict[str, dict]) -> dict[str, dict]:
    """注入归一化 key 与别名映射 key，让 ``m in pricing`` / ``len`` 与可计价集合一致。

    - 每个 modelId 的归一化形式（``GPT-5.1-Codex`` → ``gpt-5.1-codex``）；
    - ``data/model_aliases.json`` 里映射到的目标（``codex-auto-review`` → ``gpt-5.5`` 的记录副本），
      这样 ``unknown_models()`` 不会把已计价标签误报为无价。
    """
    out = dict(table)
    for key, value in table.items():
        alias = normalize_model(key)
        if alias and alias not in out:
            out[alias] = value
    for src, spec in load_aliases().items():
        if src in out:
            continue
        target = str(spec.get("model") or "")
        if target and target in out:
            copy = dict(out[target])                 # 副本：不与目标记录共享可变对象
            copy["_alias_of"] = target               # 标记来源，供 lookup 转别名路径
            out[src] = copy
    return out


def _layers(path: str | None) -> list[tuple[str, str, bool]]:
    """参与合并的层，**低 → 高**优先级：(来源标签, 路径, 是否内置资源)。

    无参：内置表（基底）→ 用户缓存 → ``CODEX_USAGE_PRICING_FILE``（后者覆盖同名项）。
    显式 ``path``：只有该文件一层（严格单文件，selfdoc/doctor 依赖这个语义）。
    """
    if path is not None:
        return [("env-file", path, False)]
    chain: list[tuple[str, str, bool]] = [
        ("builtin", builtin_path(), True),
        ("user-cache", config.cache_pricing_file(), False),
        ("env-file", config.pricing_file(), False),
    ]
    dedup: dict[str, tuple[str, str, bool]] = {}       # 同路径只留最高优先级的标签
    for source, target, is_builtin in chain:
        key = "builtin" if is_builtin else os.path.abspath(target)
        dedup[key] = (source, target, is_builtin)
    return list(dedup.values())


def _empty_meta() -> dict:
    return {"source": "builtin", "path": builtin_path(), "models": 0, "updated": None, "layers": []}


def _resolve(path: str | None = None) -> tuple[dict[str, dict], dict, str]:
    """按层合并 → (带别名的表, 元数据, source)。

    某层缺失/损坏/为空只跳过该层；全空时返回空表 + 内置表元数据。同名 modelId 由
    更高优先级的层覆盖（内置表是基底，用户的私有定价与覆盖仍然生效）。
    """
    merged: dict[str, dict] = {}
    layers: list[dict] = []
    for source, target, is_builtin in _layers(path):
        table, meta = _read_pricing(target, builtin=is_builtin)
        if not table:
            continue
        merged.update(table)                            # 后写的层覆盖同名项
        layers.append({"source": source, "path": meta["path"],
                       "models": meta["models"], "updated": meta["updated"]})
    if not merged:
        return {}, _empty_meta(), "builtin"
    user_layers = [layer for layer in layers if layer["source"] in ("env-file", "user-cache")]
    top = user_layers[-1] if user_layers else layers[0]
    meta = {
        "source": "+".join(layer["source"] for layer in layers),
        "path": top["path"],
        "models": len(merged),                          # 合并后真实条数（不含归一化别名）
        "updated": max((layer["updated"] for layer in layers if layer["updated"]), default=None),
        "layers": layers,
    }
    return _with_aliases(merged), meta, meta["source"]


# ---------------------------------------------------------------- 公开接口


def load_pricing(path: str | None = None) -> dict[str, dict]:
    """加载定价表 → {modelId: {inputCostPerMillion, cacheReadCostPerMillion, outputCostPerMillion}}。

    无参：**合并**内置表（基底）→ 用户缓存 → ``CODEX_USAGE_PRICING_FILE``；同名 modelId
    被更高优先级的层覆盖。某层缺失/损坏/为空只跳过该层，三层都不可用返回空表。
    传入 ``path`` 时严格只读该文件（找不到返回空表，不回退不合并），供 doctor 等判断指定文件状态。
    """
    return _resolve(path)[0]


def _cost_from_record(record: dict, net_in: int, cached: int, out: int) -> tuple[float | None, list[str]]:
    """按一条价格记录算成本 → (cost, fallbacks)；缺 input 价 → (None, [])。"""
    input_price = _as_price(record.get("inputCostPerMillion"))
    if input_price is None:                      # 缺 input 价 = 无定价
        return None, []
    fallbacks: list[str] = []
    cache_price = _as_price(record.get("cacheReadCostPerMillion"))
    if not cache_price:                          # None 或 0 → 回退 input 价
        cache_price = input_price
        fallbacks.append("cacheReadCostPerMillion")
    output_price = _as_price(record.get("outputCostPerMillion")) or 0.0
    cost = (max(0, net_in) * input_price
            + max(0, cached) * cache_price
            + max(0, out) * output_price) / 1e6
    return cost, fallbacks


def _scaled_record(record: dict, multiplier: float) -> dict:
    """按倍率缩放一条价格记录（档位价表缺该模型时用官方倍率兜底）。"""
    factor = max(0.0, float(multiplier))

    def scaled(key: str):
        raw = _as_price(record.get(key))
        return None if raw is None else round(raw * factor, 12)

    return {"modelId": record.get("modelId"),
            "inputCostPerMillion": scaled("inputCostPerMillion"),
            "cacheReadCostPerMillion": scaled("cacheReadCostPerMillion"),
            "outputCostPerMillion": scaled("outputCostPerMillion")}


def tier_multiplier(pricing: dict[str, dict], model: str, tier: str | None = None,
                    *, config_tier: str | None = None) -> float | None:
    """该模型在目标档位的倍率（standard = 1.0）；无公开档位价返回 None。

    优先用逐模型档位价（``data/tier_pricing.json``），否则回退官方倍率表。
    """
    effective = resolve_tier(tier, config_tier=config_tier)
    if effective == TIER_STANDARD:
        return 1.0
    hit = _lookup_hit(pricing, model)
    if hit is None:
        return None
    key, record, _alias = hit
    data = load_tier_pricing()
    tier_record = data.get(effective, {}).get(key.strip().lower())
    if tier_record:
        base = _as_price(record.get("inputCostPerMillion"))
        priced = _as_price(tier_record.get("inputCostPerMillion"))
        if base and priced:
            return round(priced / base, 4)
    return data["multipliers"].get(key.strip().lower())


def model_cost_detail(pricing: dict[str, dict], model: str, net_in: int, cached: int, out: int,
                      *, tier: str | None = None, config_tier: str | None = None) -> dict | None:
    """`model_cost` 的明细版：成本 + 命中的定价 key + 档位/别名/回退诊断。

    返回 ``{"model", "matched", "cost_usd", "fallbacks", "standard_cost_usd", "tier",
    "tier_priced"}``，别名命中时另有 ``priced_as`` / ``assumed``，用逐模型档位价时
    另有 ``tier_confidence``（``official`` / ``litellm`` / ``multiplier``）；无定价返回 None。

    - **档位**（``tier``）：``priority``/``fast`` 用 Fast 档价；``flex`` 用 Flex 档价；
      ``standard``/``default``/未知/``None`` 一律标准价（``None`` 先按
      ``config_tier`` → ``~/.codex/config.toml`` 的 service_tier → ``default``）。
      该模型没有公开档位价时退回标准价并把 ``tier_priced`` 置 False。
    - **别名**：``codex-auto-review`` 等无公开价的标签按 ``data/model_aliases.json``
      映射到目标模型并标 ``assumed: True``；映射目标本身无价则仍返回 None（标 ``*``）。
    - **回退**：表里没有 cache read 价或显式为 0 → 缓存读按 input 价计（保守上界），
      记入 ``fallbacks``；input 价缺失/非法/为负 → 整行无定价返回 None；负 token 分量按 0。
    """
    hit = _lookup_hit(pricing, model)
    if hit is None:
        return None
    key, record, alias = hit
    standard_cost, fallbacks = _cost_from_record(record, net_in, cached, out)
    if standard_cost is None:                    # 缺 input 价 = 无定价
        return None

    effective = resolve_tier(tier, config_tier=config_tier)
    cost, cost_fallbacks = standard_cost, fallbacks
    tier_priced, tier_confidence = False, None
    if effective != TIER_STANDARD:
        data = load_tier_pricing()
        tkey = key.strip().lower()
        tier_record = data.get(effective, {}).get(tkey)
        if tier_record:
            priced, priced_fallbacks = _cost_from_record(tier_record, net_in, cached, out)
            if priced is not None:
                cost, cost_fallbacks = priced, priced_fallbacks
                tier_priced = True
                tier_confidence = tier_record.get("confidence") or "litellm"
        if not tier_priced:
            mult = data["multipliers"].get(tkey)
            if mult:
                priced, priced_fallbacks = _cost_from_record(
                    _scaled_record(record, mult), net_in, cached, out)
                if priced is not None:
                    cost, cost_fallbacks = priced, priced_fallbacks
                    tier_priced = True
                    tier_confidence = "multiplier"

    detail = {
        "model": model,
        "matched": key,
        "cost_usd": cost,
        "fallbacks": cost_fallbacks,
        "standard_cost_usd": standard_cost,
        "tier": effective,
        "tier_priced": tier_priced,
    }
    if tier_confidence:
        detail["tier_confidence"] = tier_confidence
    if alias is not None:
        detail["priced_as"] = str(alias.get("model"))
        detail["assumed"] = bool(alias.get("assumed", True))
    return detail


def model_cost(pricing: dict[str, dict], model: str, net_in: int, cached: int, out: int,
               *, tier: str | None = None, config_tier: str | None = None) -> float | None:
    """单模型成本（USD）；无定价模型返回 None（调用方按 $0 计并标注 *）。

    ``tier`` 给 ``priority``/``fast``/``flex`` 时按对应档位价计（默认标准价）；
    诊断（是否回退、是否别名映射、档位价置信度）用 ``model_cost_detail()``。
    """
    detail = model_cost_detail(pricing, model, net_in, cached, out,
                               tier=tier, config_tier=config_tier)
    return detail["cost_usd"] if detail else None


def cost_for_tiered(tiers: dict[str, dict[str, list[int]]], pricing: dict[str, dict],
                    *, config_tier: str | None = None) -> dict:
    """按 ``Session.tiers``（``{model: {tier: [gross_in, cached, out, ...]}}``）分档计价。

    返回 ``{"cost_usd", "all_priced", "models": {model: {"cost_usd", "tiers": {...}}}}``，
    供 stats/cli 接入（每个 (模型, 档位) 槽单独计价，槽位语义与 ``Session.models`` 一致）。
    """
    total, all_priced = 0.0, True
    models: dict[str, dict] = {}
    for model, slots in (tiers or {}).items():
        model_total = 0.0
        per_tier: dict[str, dict] = {}
        for tier, slot in (slots or {}).items():
            gross, cached, out = int(slot[0]), int(slot[1]), int(slot[2])
            detail = model_cost_detail(pricing, model, gross - cached, cached, out,
                                       tier=tier, config_tier=config_tier)
            if detail is None:
                all_priced = False
                cost = 0.0
            else:
                cost = detail["cost_usd"]
            model_total += cost
            per_tier[tier] = {"cost_usd": cost, "priced": detail is not None,
                              "tier": detail["tier"] if detail else None}
        models[model] = {"cost_usd": model_total, "tiers": per_tier}
        total += model_total
    return {"cost_usd": total, "all_priced": all_priced, "models": models}


def cache_read_coverage(pricing: dict[str, dict]) -> dict:
    """cache read 价覆盖统计（供 ``--doctor`` 诊断回退影响）。

    缺价（缺失或显式 0）的条目在计费时会回退 input 价：::

        {"models": 2086, "cache_read_missing": 717, "cache_read_missing_pct": 34.4}
    """
    total = len(pricing)
    missing = sum(1 for row in pricing.values()
                  if not _as_price(row.get("cacheReadCostPerMillion")))
    return {"models": total, "cache_read_missing": missing,
            "cache_read_missing_pct": round(missing * 100 / total, 1) if total else 0.0}


def source_info() -> dict:
    """当前生效的定价来源（合并结果）。

    ::

        {"source": "builtin+user-cache+env-file",   # 生效的层，低→高优先级
         "path": "/…/model-pricing.json",           # 最高优先级层路径（用户层优先，否则内置表）
         "models": 2090,                            # 合并后真实条数（不含归一化别名）
         "updated": "2026-09-13T11:16:39+00:00",    # 各层里最新的 updated
         "layers": [{"source": "builtin", "path": ..., "models": 2086, "updated": ...}, ...]}

    判断某层是否生效可用 ``"env-file" in info["source"]``（或遍历 ``layers``）。
    """
    table, meta, _source = _resolve()
    info = {
        "source": meta["source"],
        "path": meta["path"],
        "models": meta["models"] or len(table),
        "updated": meta["updated"],
        "layers": meta["layers"],
    }
    return info


# ---------------------------------------------------------------- 渠道解析


def _as_price(value) -> float | None:
    """成本数值校验：None/非数/负数 → None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


def _is_non_text(model_id: str, mode=None) -> bool:
    if isinstance(mode, str) and any(tok in mode.lower() for tok in _NON_TEXT_MODES):
        return True
    return bool(_NON_TEXT_RE.search(model_id.lower()))


def clean_model_id(model_id: str) -> str:
    """渠道 model id → 通用模型名：剥 provider 前缀（最多 3 段），保留原始大小写。"""
    s = (model_id or "").strip()
    for _ in range(3):
        stripped = _PROVIDER_PREFIX_RE.sub("", s)
        if stripped == s:
            break
        s = stripped
    return s


def _record(model_id: str, input_price, output_price, cache_read) -> dict | None:
    pin, pout = _as_price(input_price), _as_price(output_price)
    if pin is None or pout is None:
        return None
    if pin == 0 and pout == 0:                  # 全 0 视为“未定价”，不冒充免费
        return None
    if _is_non_text(model_id):
        return None
    return {
        "modelId": model_id,
        "inputCostPerMillion": round(pin, 6),
        "cacheReadCostPerMillion": round(_as_price(cache_read) or 0.0, 6),
        "outputCostPerMillion": round(pout, 6),
    }


def _sort_key(provider_id: str) -> tuple[int, str]:
    return (_PRIORITY_INDEX.get(provider_id, len(PROVIDER_PRIORITY)), provider_id)


def _provider_entry_key(entry: tuple) -> tuple[int, str]:
    """按 provider 权威度排序渠道条目（条目第 0 位是 provider id）。"""
    return _sort_key(entry[0])


def records_from_modelsdev(raw) -> list[dict]:
    """models.dev/api.json → cc-switch 兼容记录（按 provider 权威度去重，$/M tokens）。

    字段映射：``cost.input`` → inputCostPerMillion、``cost.output`` → outputCostPerMillion、
    ``cost.cache_read`` → cacheReadCostPerMillion；``cost.cache_write`` 无对应字段（不参与成本口径）。
    """
    if not isinstance(raw, dict):
        return []
    providers = [(pid, p) for pid, p in raw.items() if isinstance(p, dict)]
    providers.sort(key=_provider_entry_key)
    seen: set[str] = set()
    records: list[dict] = []
    for _pid, provider in providers:
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model_id, model in models.items():
            if not isinstance(model, dict):
                continue
            cost = model.get("cost")
            if not isinstance(cost, dict):
                continue
            key = clean_model_id(model_id)
            if not key or key in seen:
                continue
            modalities = model.get("modalities")
            mode = None
            if isinstance(modalities, dict):
                outputs = modalities.get("output")
                if isinstance(outputs, list) and outputs and "text" not in outputs:
                    mode = "image"          # 只出图/只出音频 → 非文本生成
            rec = _record(key, cost.get("input"), cost.get("output"), cost.get("cache_read"))
            if rec is None or _is_non_text(key, mode):
                continue
            seen.add(key)
            records.append(rec)
    return records


def _per_million(value) -> float | None:
    """LiteLLM 的 $/token → $/M tokens。"""
    if value is None:
        return None
    try:
        return float(value) * 1e6
    except (TypeError, ValueError):
        return None


def records_from_litellm(raw) -> list[dict]:
    """LiteLLM JSON → cc-switch 兼容记录（$/token ×1e6 → $/M tokens）。"""
    if not isinstance(raw, dict):
        return []
    entries = []
    for model_id, model in raw.items():
        if not isinstance(model, dict):
            continue
        if model_id in ("sample_spec",):
            continue
        provider = model.get("litellm_provider")
        entries.append((provider if isinstance(provider, str) and provider else "", model_id, model))
    entries.sort(key=_provider_entry_key)
    seen: set[str] = set()
    records: list[dict] = []
    for _provider, model_id, model in entries:
        key = clean_model_id(model_id)
        if not key or key in seen:
            continue
        rec = _record(key,
                      _per_million(model.get("input_cost_per_token")),
                      _per_million(model.get("output_cost_per_token")),
                      _per_million(model.get("cache_read_input_token_cost")))
        if rec is None or _is_non_text(key, model.get("mode")):
            continue
        seen.add(key)
        records.append(rec)
    return records


def _record_id_key(record: dict) -> str:
    return str(record.get("modelId", ""))


def tier_records_from_litellm(raw) -> dict:
    """LiteLLM 快照 → 档位价数据 ``{"priority": [...], "flex": [...], "multipliers": {...}}``。

    只取**裸名**条目（无 provider 前缀）的 ``*_priority`` / ``*_flex`` 字段（$/token → $/M）。
    ``confidence``：``official`` = OpenAI 官方 Fast/Flex 价目表有独立行；``litellm`` = 只有
    第三方快照（5.1/5.2/5.3-codex 这类官方无 Fast 行的模型，标低置信）。
    ``multipliers`` 仅收录官方档位模型（逐模型倍率，避免“统一 2×”在 5.5 上少算 20%）。
    """
    rows: dict = {"priority": [], "flex": [], "multipliers": {}}
    if not isinstance(raw, dict):
        return rows
    for model_id, model in raw.items():
        if not isinstance(model, dict) or model_id == "sample_spec" or "/" in model_id:
            continue
        key = clean_model_id(model_id)
        if not key:
            continue
        for tier in ("priority", "flex"):
            rec = _record(key,
                          _per_million(model.get(f"input_cost_per_token_{tier}")),
                          _per_million(model.get(f"output_cost_per_token_{tier}")),
                          _per_million(model.get(f"cache_read_input_token_cost_{tier}")))
            if rec is None or _is_non_text(key, model.get("mode")):
                continue
            rec["confidence"] = "official" if key.lower() in OFFICIAL_TIER_MODELS else "litellm"
            rows[tier].append(rec)
        base_input = _per_million(model.get("input_cost_per_token"))
        priority_input = _per_million(model.get("input_cost_per_token_priority"))
        if base_input and priority_input and key.lower() in OFFICIAL_TIER_MODELS:
            rows["multipliers"][key.lower()] = round(priority_input / base_input, 4)
    for tier in ("priority", "flex"):
        seen, unique = set(), []
        for rec in sorted(rows[tier], key=_record_id_key):
            if rec["modelId"] in seen:
                continue
            seen.add(rec["modelId"])
            unique.append(rec)
        rows[tier] = unique
    return rows


def records_from(source: str, raw) -> list[dict]:
    """按渠道名解析原始 JSON → cc-switch 兼容记录。"""
    fmt = (SOURCES.get(source) or {}).get("format")
    if fmt == "models-dev":
        return records_from_modelsdev(raw)
    if fmt == "litellm":
        return records_from_litellm(raw)
    raise ValueError(f"未知定价渠道: {source}（可选: {', '.join(SOURCES)}）")


# ---------------------------------------------------------------- 同步


_urlopen = urllib.request.urlopen       # 仅供测试 monkeypatch


def _fetch_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": f"codex-usage/{_package_version()}",
        "Accept": "application/json",
    })
    resp = _urlopen(request, timeout=timeout)
    try:
        data = resp.read()
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            close()
    return data.decode("utf-8") if isinstance(data, bytes) else str(data)


def _package_version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "0"


def _write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pricing-", suffix=".json.tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dump_table_text(payload: dict) -> str:
    """定价表文本：每条模型一行，更新内置表时 git diff 干净、体积紧凑。"""
    records = payload.get("models") or []
    lines = [
        "{",
        f'  "source": {json.dumps(payload.get("source"), ensure_ascii=False)},',
        f'  "updated": {json.dumps(payload.get("updated"), ensure_ascii=False)},',
        '  "models": [',
    ]
    for i, rec in enumerate(records):
        lines.append("    " + json.dumps(rec, ensure_ascii=False, separators=(", ", ": "))
                     + ("," if i < len(records) - 1 else ""))
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def fetch_source(source: str, timeout: float = 20.0) -> object:
    """下载渠道原始 JSON（失败抛异常）。"""
    if source not in SOURCES:
        raise ValueError(f"未知定价渠道: {source}（可选: {', '.join(SOURCES)}）")
    url = SOURCES[source]["url"]
    raw = json.loads(_fetch_text(url, timeout))
    if not isinstance(raw, (dict, list)):
        raise RuntimeError(f"渠道 {source} 返回了非 JSON 对象: {type(raw).__name__}")
    return raw


def write_pricing_table(path: str, records: list[dict], *, source: str = "builtin",
                        updated: str | None = None) -> str:
    """把记录写成 cc-switch 兼容定价表（原子写，每条一行），返回路径。"""
    payload = {
        "source": source,
        "updated": updated or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": records,
    }
    _write_text_atomic(path, _dump_table_text(payload))
    return path


def sync(source: str = DEFAULT_SOURCE, timeout: float = 20.0) -> dict:
    """拉取公开渠道 → 写用户缓存 → {"path", "models", "source"}；失败抛异常（由 cli 捕获）。"""
    raw = fetch_source(source, timeout)
    records = records_from(source, raw)
    if not records:
        raise RuntimeError(f"渠道 {source} 未返回可用定价（{SOURCES[source]['url']}）")
    path = config.cache_pricing_file()
    write_pricing_table(path, records, source=source)
    return {"path": path, "models": len(records), "source": source}
