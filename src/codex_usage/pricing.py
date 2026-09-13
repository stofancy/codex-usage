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


def lookup(pricing: dict[str, dict], model: str) -> dict | None:
    """按 精确 → 归一化 → 前缀 三档查找价格记录；找不到返回 None。"""
    if not pricing or not model:
        return None
    hit = pricing.get(model)
    if hit is not None:
        return hit
    n = normalize_model(model)
    if not n:
        return None
    hit = pricing.get(n)
    if hit is not None:
        return hit
    key = _prefix_lookup(pricing, n)
    return pricing[key] if key else None


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


def _with_aliases(table: dict[str, dict]) -> dict[str, dict]:
    """把每个 modelId 的归一化形式也作为别名 key 注入，让 ``m in pricing`` 判定一致。"""
    out = dict(table)
    for key, value in table.items():
        alias = normalize_model(key)
        if alias and alias not in out:
            out[alias] = value
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


def model_cost(pricing: dict[str, dict], model: str, net_in: int, cached: int, out: int) -> float | None:
    """单模型成本（USD）；无定价模型返回 None（调用方按 $0 计并标注 *）。"""
    p = lookup(pricing, model)
    if not p:
        return None

    def per_million(key: str) -> float:
        return float(p.get(key) or 0)

    try:
        return (net_in * per_million("inputCostPerMillion")
                + cached * per_million("cacheReadCostPerMillion")
                + out * per_million("outputCostPerMillion")) / 1e6
    except Exception:
        return None


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
