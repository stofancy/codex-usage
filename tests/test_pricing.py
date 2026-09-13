"""定价模块测试：内置表、模型名匹配、加载优先级回退、渠道解析与 sync。

全部离网可跑：sync 用 monkeypatch 替换 ``pricing._urlopen``，不发起真实网络请求；
用户目录通过环境变量隔离到 tmp_path，不依赖本机 ~/.cc-switch 或 ~/.cache。
"""

import importlib.resources
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from codex_usage import pricing

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 夹具


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """把 env-file 与用户缓存都挪到 tmp，保证测试与真实用户环境无关。"""
    env_file = tmp_path / "cc-switch-pricing.json"
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("CODEX_USAGE_PRICING_FILE", str(env_file))
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(cache_dir))
    # 数据文件/配置读取都有进程内缓存：每个用例前后清掉，避免相互污染
    caches = (pricing.load_aliases, pricing.load_tier_pricing, pricing.default_service_tier)
    for cached in caches:
        cached.cache_clear()
    yield {"env_file": env_file, "cache_dir": cache_dir, "cache_file": cache_dir / "pricing.json"}
    for cached in caches:
        cached.cache_clear()


def cc_switch_table(rows, updated=None):
    payload = {"models": rows}
    if updated:
        payload["updated"] = updated
    return json.dumps(payload, ensure_ascii=False)


def price(input_, output, cache_read=0.0):
    return {"inputCostPerMillion": input_, "cacheReadCostPerMillion": cache_read,
            "outputCostPerMillion": output}


def write_table(path: Path, rows, updated=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cc_switch_table(rows, updated), encoding="utf-8")
    return path


def fake_urlopen_factory(payload):
    """假的 _urlopen：返回可直接 read() 的 BytesIO。"""
    def fake_urlopen(request, timeout=None):
        body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return io.BytesIO(body.encode("utf-8"))
    return fake_urlopen


# ---------------------------------------------------------------- 内置表


def test_builtin_table_loads_with_prices(isolated):
    """内置表可直接离线加载，至少 10 个模型有价，且覆盖 codex / claude 系列。"""
    table = pricing.load_pricing()
    assert len(table) >= 10
    known = {m: v for m, v in table.items() if float(v.get("inputCostPerMillion") or 0) > 0}
    assert len(known) >= 10
    assert any(m in table for m in ("gpt-5.1-codex", "gpt-5.2-codex", "gpt-5-codex"))
    assert any(m.startswith("claude-") for m in table)
    for row in table.values():
        assert float(row["inputCostPerMillion"]) >= 0
        assert float(row["outputCostPerMillion"]) >= 0
        assert "cacheReadCostPerMillion" in row


def test_builtin_table_is_cc_switch_format():
    """内置文件是 cc-switch 兼容格式：{"models": [{modelId, 三个成本字段}]}。"""
    text = importlib.resources.files("codex_usage").joinpath("data", "pricing.json").read_text(
        encoding="utf-8")
    raw = json.loads(text)
    assert isinstance(raw["models"], list) and len(raw["models"]) >= 10
    assert raw.get("updated")
    fields = {"modelId", "inputCostPerMillion", "cacheReadCostPerMillion", "outputCostPerMillion"}
    for row in raw["models"]:
        assert fields.issubset(row)
        assert isinstance(row["modelId"], str) and row["modelId"]
        assert all(isinstance(row[k], (int, float)) for k in fields - {"modelId"})


def test_builtin_table_has_codex_and_claude_prices(isolated):
    """公开用户开箱即用的成本：内置表能算出真实 Codex/Claude 模型的非 0 成本。"""
    table = pricing.load_pricing()
    for model in ("gpt-5.1-codex", "gpt-5.2-codex", "gpt-5-codex"):
        if model in table:
            assert pricing.model_cost(table, model, 1_000_000, 0, 0) > 0
    claude = next(m for m in table if m.startswith("claude-"))
    assert pricing.model_cost(table, claude, 1_000_000, 0, 0) > 0


def test_source_info_builtin(isolated):
    info = pricing.source_info()
    assert info["source"] == "builtin"
    assert info["models"] >= 10
    assert info["updated"]
    assert info["path"].endswith("pricing.json")


# ---------------------------------------------------------------- 只来自公开渠道


def test_generated_prices_come_from_channel_data():
    """生成逻辑只吃渠道 JSON：渠道里有的收（含 gpt-6-astra），渠道没有的不可能出现。"""
    raw = {"openai": {"models": {
        "gpt-6-astra": {"cost": {"input": 10, "output": 50, "cache_read": 1}},
        "gpt-5.6-sol": {"cost": {"input": 4, "output": 20}},
    }}}
    records = {r["modelId"]: r for r in pricing.records_from_modelsdev(raw)}
    assert set(records) == {"gpt-6-astra", "gpt-5.6-sol"}
    assert records["gpt-6-astra"]["inputCostPerMillion"] == pytest.approx(10.0)
    assert records["gpt-6-astra"]["cacheReadCostPerMillion"] == pytest.approx(1.0)


def test_builtin_matches_channel_catalog(isolated):
    """内置表是公开渠道快照：公开条目有价；渠道里没有的名字不会凭空出现。"""
    raw = json.loads(importlib.resources.files("codex_usage").joinpath(
        "data", "pricing.json").read_text(encoding="utf-8"))
    ids = {r["modelId"] for r in raw["models"]}
    assert "gpt-6-astra" in ids                       # models.dev 公开条目（9 个 provider）
    assert not (ids & {"gpt-reserve", "codex-auto-review"})   # 渠道 0 条 → 内置文件不含
    table = pricing.load_pricing()
    assert pricing.model_cost(table, "gpt-6-astra", 1000, 500, 200) > 0
    # codex-auto-review 走别名映射（标 assumed）；gpt-reserve 无公开价、不臆造 → 仍无价
    detail = pricing.model_cost_detail(table, "codex-auto-review", 1_000_000, 0, 0)
    assert detail["priced_as"] == "gpt-5.5" and detail["assumed"] is True
    assert detail["cost_usd"] == pytest.approx(5.0)
    assert pricing.model_cost(table, "gpt-reserve", 1_000_000, 0, 0) is None


def test_builtin_table_never_merges_env_file_entries(isolated):
    """内置资源文件是生成产物，不并入 env-file 私有条目（env 只在运行时参与合并）。"""
    write_table(isolated["env_file"], [{"modelId": "priv-model-x", **price(1, 2)}])
    assert "priv-model-x" in pricing.load_pricing()           # 运行时合并可见
    raw = json.loads(importlib.resources.files("codex_usage").joinpath(
        "data", "pricing.json").read_text(encoding="utf-8"))
    assert "priv-model-x" not in {r["modelId"] for r in raw["models"]}


def test_builtin_covers_openai_catalog_and_codex_family(isolated):
    """内置表覆盖 openai 官方目录常用模型 + 第三方的 codex 变体系列（Lead 的验收目标）。"""
    table = pricing.load_pricing()
    openai_common = ("gpt-5", "gpt-5.1", "gpt-5.2", "gpt-5.3-codex", "gpt-5.3-codex-spark",
                     "gpt-5.4", "gpt-5.4-mini", "gpt-5.5", "gpt-5.6", "gpt-5.6-luna",
                     "gpt-5.6-sol", "gpt-5.6-terra", "o3", "o4-mini", "gpt-4.1", "gpt-4o")
    codex_family = ("gpt-5-codex", "gpt-5.1-codex", "gpt-5.1-codex-mini", "gpt-5.1-codex-max",
                    "gpt-5.2-codex", "gpt-5.3-codex", "codex-mini")
    missing = [m for m in openai_common + codex_family
               if pricing.model_cost(table, m, 1_000_000, 0, 0) is None]
    assert not missing, f"内置表缺价: {missing}"
    # codex 变体的价格取渠道权威价（1.25/10/0.125）
    assert pricing.model_cost(table, "gpt-5.1-codex", 1_000_000, 1_000_000, 0) == pytest.approx(1.375)
    # 公开登记的 gpt-6-astra 现在有价（不再被脱敏名单挡住）
    assert pricing.model_cost(table, "gpt-6-astra", 1000, 500, 200) > 0


# ---------------------------------------------------------------- 归一化与匹配


def test_normalize_model():
    assert pricing.normalize_model("gpt-5.1-codex-2025-11-13") == "gpt-5.1-codex"
    assert pricing.normalize_model("gpt-5.1-codex-20251113") == "gpt-5.1-codex"
    assert pricing.normalize_model("GPT-5.1-Codex") == "gpt-5.1-codex"
    assert pricing.normalize_model("openrouter/openai/gpt-5.2-codex") == "gpt-5.2-codex"
    assert pricing.normalize_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"
    assert pricing.normalize_model("codex-mini-latest") == "codex-mini"
    assert pricing.normalize_model("claude-3.5-sonnet") == "claude-3-5-sonnet"
    assert pricing.normalize_model("") == ""
    assert pricing.normalize_model(None) == ""
    # 幂等：别名注入依赖这个性质
    for name in ("GPT-5.1-Codex-2025-11-13", "openrouter/openai/gpt-5.2-codex", "codex-mini-latest"):
        once = pricing.normalize_model(name)
        assert pricing.normalize_model(once) == once


def test_lookup_exact_normalized_prefix():
    flat = {"gpt-5.1-codex": price(1.25, 10, 0.125)}
    assert pricing.lookup(flat, "gpt-5.1-codex") is flat["gpt-5.1-codex"]
    assert pricing.lookup(flat, "gpt-5.1-codex-2025-11-13") is flat["gpt-5.1-codex"]
    assert pricing.lookup(flat, "GPT-5.1-Codex") is flat["gpt-5.1-codex"]
    assert pricing.lookup(flat, "unknown-model") is None
    assert pricing.lookup({}, "gpt-5.1-codex") is None


def test_prefix_lookup_matches_variant_and_prefers_longest():
    flat = {"gpt-5.6": price(1.0, 5), "gpt-5.6-sol": price(4.0, 20)}
    assert pricing.lookup(flat, "gpt-5.6-sol-yytoken")["inputCostPerMillion"] == 4.0


def test_prefix_lookup_rejects_over_generic_key():
    """``gpt`` 这类过泛条目不能把私有模型 gpt-reserve 误算成它的价。"""
    flat = {"gpt": price(10, 30), "o3": price(2, 8)}
    assert pricing.lookup(flat, "gpt-reserve") is None
    assert pricing.lookup(flat, "codex-auto-review") is None


def test_model_cost_units_and_unknown():
    table = {"gpt-5.1-codex": price(1.25, 10, 0.125)}
    # 1M 净输入 + 1M 缓存读 + 1M 输出 = 1.25 + 0.125 + 10
    assert pricing.model_cost(table, "gpt-5.1-codex", 1_000_000, 1_000_000, 1_000_000) == pytest.approx(11.375)
    assert pricing.model_cost(table, "gpt-5.1-codex-2025-11-13", 1_000_000, 0, 0) == pytest.approx(1.25)
    assert pricing.model_cost(table, "gpt-mystery", 1_000_000, 0, 0) is None


def test_model_cost_accepts_string_prices():
    """cc-switch 文件里的价格常写成字符串，照旧可用。"""
    table = {"gpt-5.6-luna": {"inputCostPerMillion": "10", "cacheReadCostPerMillion": "1",
                              "outputCostPerMillion": "50"}}
    assert pricing.model_cost(table, "gpt-5.6-luna", 1_000_000, 0, 0) == pytest.approx(10.0)


# ---------------------------------------------------------------- cache_read 价回退


def test_cache_read_falls_back_to_input_when_missing():
    """表里没有 cache read 价 → 缓存读按 input 价计（保守上界），并可在明细里看出来。"""
    table = {"m": {"inputCostPerMillion": 10, "outputCostPerMillion": 20}}
    assert pricing.model_cost(table, "m", 1_000_000, 1_000_000, 0) == pytest.approx(20.0)
    detail = pricing.model_cost_detail(table, "m", 1_000_000, 1_000_000, 0)
    assert detail["matched"] == "m"
    assert detail["cost_usd"] == pytest.approx(20.0)
    assert detail["fallbacks"] == ["cacheReadCostPerMillion"]


def test_cache_read_falls_back_when_explicit_zero():
    """显式 cache read = 0（含 cc-switch 字符串写法）同样回退到 input 价。"""
    table = {"m": {"inputCostPerMillion": "10", "cacheReadCostPerMillion": "0",
                   "outputCostPerMillion": "20"}}
    assert pricing.model_cost(table, "m", 0, 1_000_000, 0) == pytest.approx(10.0)
    detail = pricing.model_cost_detail(table, "m", 0, 1_000_000, 0)
    assert detail["fallbacks"] == ["cacheReadCostPerMillion"]


def test_cache_read_price_is_used_when_present():
    """cache read 价正常时行为不变，也不算“用了回退”。"""
    table = {"m": {"inputCostPerMillion": 10, "cacheReadCostPerMillion": 1,
                   "outputCostPerMillion": 20}}
    assert pricing.model_cost(table, "m", 1_000_000, 1_000_000, 0) == pytest.approx(11.0)
    assert pricing.model_cost_detail(table, "m", 1_000_000, 1_000_000, 0)["fallbacks"] == []


def test_missing_input_price_is_unpriced():
    """缺 input 价（缺失 / None / 负数）→ 整行无定价，返回 None。"""
    for row in ({"outputCostPerMillion": 20, "cacheReadCostPerMillion": 1},
                {"inputCostPerMillion": None, "outputCostPerMillion": 20},
                {"inputCostPerMillion": -1, "outputCostPerMillion": 20}):
        table = {"m": row}
        assert pricing.model_cost(table, "m", 1_000_000, 1_000_000, 1_000_000) is None
        assert pricing.model_cost_detail(table, "m", 1_000_000, 1_000_000, 1_000_000) is None


def test_zero_and_negative_components_never_negative():
    """任一分量为 0 不出异常；负分量按 0 计，成本不为负。"""
    table = {
        "fallback": {"inputCostPerMillion": 10, "outputCostPerMillion": 20},
        "normal": {"inputCostPerMillion": 10, "cacheReadCostPerMillion": 1, "outputCostPerMillion": 20},
    }
    for model in table:
        assert pricing.model_cost(table, model, 0, 0, 0) == 0.0
        cost = pricing.model_cost(table, model, -10, -10, -10)
        assert cost == 0.0 and cost >= 0


def test_model_cost_detail_matches_model_cost_and_reports_match():
    table = {"gpt-5.6-sol": {"inputCostPerMillion": 4, "outputCostPerMillion": 20}}
    detail = pricing.model_cost_detail(table, "gpt-5.6-sol-yytoken", 0, 1_000_000, 0)
    assert detail["matched"] == "gpt-5.6-sol"                    # 前缀兜底命中的表内 key
    assert detail["cost_usd"] == pytest.approx(4.0)              # 回退 input 价
    assert detail["cost_usd"] == pricing.model_cost(table, "gpt-5.6-sol-yytoken", 0, 1_000_000, 0)
    assert pricing.model_cost_detail(table, "unknown", 1, 1, 1) is None


def test_builtin_table_has_cache_read_gap():
    """内置表确实存在 cache read 覆盖缺口（回退规则的前提），但不是全局缺失。"""
    raw = json.loads(importlib.resources.files("codex_usage").joinpath(
        "data", "pricing.json").read_text(encoding="utf-8"))
    rows = raw["models"]
    missing = [r for r in rows if not (r.get("cacheReadCostPerMillion") or 0)]
    assert 0 < len(missing) < len(rows)
    # 典型缺口：pro 系列官方只给 input/output
    ids = {r["modelId"] for r in missing}
    assert {"gpt-5-pro", "gpt-5.2-pro"} & ids


def test_cache_read_coverage_counts_fallbacks():
    table = {
        "no-cache": {"inputCostPerMillion": 1, "outputCostPerMillion": 2},
        "zero-cache": {"inputCostPerMillion": 1, "cacheReadCostPerMillion": 0,
                       "outputCostPerMillion": 2},
        "has-cache": {"inputCostPerMillion": 1, "cacheReadCostPerMillion": 0.1,
                      "outputCostPerMillion": 2},
    }
    assert pricing.cache_read_coverage(table) == {
        "models": 3, "cache_read_missing": 2, "cache_read_missing_pct": 66.7}
    assert pricing.cache_read_coverage({})["models"] == 0


# ---------------------------------------------------------------- 合并加载与回退


def test_merge_builtin_base_with_user_overrides(isolated):
    """内置表为基底，缓存与 env-file 按 modelId 覆盖，私有模型同时可见。"""
    env_file, cache_file = isolated["env_file"], isolated["cache_file"]
    write_table(cache_file, [{"modelId": "gpt-5.1-codex", **price(7, 7, 0.7)},
                             {"modelId": "cache-only", **price(2, 4)}])
    write_table(env_file, [{"modelId": "gpt-5.1-codex", **price(9, 9, 0.9)},
                           {"modelId": "env-only", **price(1, 3)}])

    table = pricing.load_pricing()
    # env-file 覆盖 cache 覆盖内置
    assert table["gpt-5.1-codex"]["inputCostPerMillion"] == pytest.approx(9.0)
    # 三层都可见：内置公开模型 + 两层私有模型
    assert "gpt-5.6-sol" in table and "cache-only" in table and "env-only" in table
    info = pricing.source_info()
    assert info["source"] == "builtin+user-cache+env-file"
    assert info["path"] == str(env_file)
    assert [layer["source"] for layer in info["layers"]] == ["builtin", "user-cache", "env-file"]
    assert info["models"] >= 10

    env_file.unlink()
    table = pricing.load_pricing()
    assert table["gpt-5.1-codex"]["inputCostPerMillion"] == pytest.approx(7.0)   # cache 覆盖内置
    assert "cache-only" in table and "env-only" not in table
    assert pricing.source_info()["source"] == "builtin+user-cache"

    cache_file.unlink()
    table = pricing.load_pricing()
    assert table["gpt-5.1-codex"]["inputCostPerMillion"] == pytest.approx(1.25)  # 回到内置价
    info = pricing.source_info()
    assert info["source"] == "builtin"
    assert info["path"] == pricing.builtin_path()
    assert info["layers"] == [{"source": "builtin", "path": pricing.builtin_path(),
                               "models": info["models"], "updated": info["updated"]}]


def test_broken_layers_are_skipped(isolated):
    """某层损坏只跳过该层，其余层照常参与合并（内置表永远在基底）。"""
    env_file, cache_file = isolated["env_file"], isolated["cache_file"]

    # env-file 坏 JSON → 缓存与内置照常合并
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cc_switch_table([{"modelId": "cache-model", **price(2, 4)}]), encoding="utf-8")
    env_file.write_text("{ this is not json", encoding="utf-8")
    table = pricing.load_pricing()
    assert "cache-model" in table and len(table) >= 10
    assert pricing.source_info()["source"] == "builtin+user-cache"

    # 空文件 / 空 models / 无 modelId 行 → 两层都跳过，仅内置表
    for broken in ("", "{}", '{"models": []}', '{"models": [{"displayName": "x"}]}', "null"):
        env_file.write_text(broken, encoding="utf-8")
        cache_file.write_text(broken, encoding="utf-8")
        table = pricing.load_pricing()
        assert len(table) >= 10, f"损坏层破坏了加载: {broken!r}"
        assert pricing.source_info()["source"] == "builtin"


def test_explicit_path_is_strict(isolated):
    """显式 path 只读该文件（doctor 用它判断“指定文件是否存在”）。"""
    custom = isolated["env_file"].parent / "custom.json"
    write_table(custom, [{"modelId": "custom-model", **price(1, 2)}])
    assert "custom-model" in pricing.load_pricing(str(custom))
    assert pricing.load_pricing("/nonexistent/pricing.json") == {}


def test_env_file_missing_falls_back_to_builtin(isolated):
    """验收路径：CODEX_USAGE_PRICING_FILE 指向缺失文件时，无参加载回退内置表并算出非 0 成本。"""
    table = pricing.load_pricing()
    assert len(table) >= 10
    info = pricing.source_info()
    assert info["source"] == "builtin"
    assert info["path"].endswith("pricing.json")
    for model in ("gpt-5.1-codex", "gpt-5.2-codex", "gpt-5-codex", "gpt-5.3-codex"):
        assert pricing.model_cost(table, model, 1000, 500, 200) > 0


def test_source_info_reports_merged_layers(isolated):
    cache_file = isolated["cache_file"]
    write_table(cache_file, [{"modelId": "a", **price(1, 2)}, {"modelId": "b", **price(3, 4)}],
                updated="2026-09-13T23:00:00+00:00")       # 比内置表 updated 更晚
    info = pricing.source_info()
    assert info["source"] == "builtin+user-cache"
    assert info["path"] == str(cache_file)
    assert info["models"] >= 10                            # 合并后条数（不含归一化别名）
    assert info["updated"] == "2026-09-13T23:00:00+00:00"  # 各层里最新
    assert [layer["source"] for layer in info["layers"]] == ["builtin", "user-cache"]
    assert info["layers"][0]["models"] >= 10
    assert info["layers"][1]["models"] == 2


# ---------------------------------------------------------------- 渠道解析


MODELSDEV_SAMPLE = {
    "openai": {"models": {
        "gpt-5.6-sol": {"name": "Sol", "cost": {"input": 4, "output": 20, "cache_read": 0.4,
                                                "cache_write": 5}},
        "gpt-free": {"cost": {"input": 0, "output": 0}},
        "text-embedding-3-small": {"cost": {"input": 0.02, "output": 0}},
        "no-cost": {"name": "no cost"},
        "gpt-image-1": {"cost": {"input": 5, "output": 30}},
    }},
    "zhipuai": {"models": {
        "glm-5.2": {"cost": {"input": 1.4, "output": 4.4, "cache_read": 0.26}},
        "glm-5.2-flash": {"cost": {"input": None, "output": None}},
    }},
    "reseller-x": {"models": {
        "gpt-5.6-sol": {"cost": {"input": 1, "output": 5}},           # 同名低价转售商
        "openrouter/openai/gpt-5.1-codex": {"cost": {"input": 1.25, "output": 10,
                                                     "cache_read": 0.125}},
    }},
}


def test_records_from_modelsdev_priority_and_cleanup():
    records = {r["modelId"]: r for r in pricing.records_from_modelsdev(MODELSDEV_SAMPLE)}
    # provider 前缀剥离
    assert "gpt-5.1-codex" in records
    assert records["gpt-5.1-codex"]["inputCostPerMillion"] == pytest.approx(1.25)
    # 官方优先于转售商（同名低价不覆盖）
    assert records["gpt-5.6-sol"]["inputCostPerMillion"] == pytest.approx(4.0)
    assert records["glm-5.2"]["cacheReadCostPerMillion"] == pytest.approx(0.26)


def test_records_filter_zero_and_non_text():
    records = {r["modelId"] for r in pricing.records_from_modelsdev(MODELSDEV_SAMPLE)}
    assert "gpt-free" not in records          # 0/0 视为未定价
    assert "no-cost" not in records           # 无 cost 字段
    assert "text-embedding-3-small" not in records
    assert "gpt-image-1" not in records
    assert "glm-5.2-flash" not in records     # cost 为 None


def test_records_from_litellm_converts_per_token():
    raw = {
        "sample_spec": {"input_cost_per_token": 0.001},
        "gpt-5.1-codex": {"input_cost_per_token": 1.25e-06, "output_cost_per_token": 1e-05,
                          "cache_read_input_token_cost": 1.25e-07, "litellm_provider": "openai"},
        "azure/gpt-5.1-codex": {"input_cost_per_token": 9e-05, "output_cost_per_token": 9e-04,
                                "litellm_provider": "azure"},
        "some-embedding": {"input_cost_per_token": 1e-07, "output_cost_per_token": 0,
                           "mode": "embedding"},
    }
    records = {r["modelId"]: r for r in pricing.records_from_litellm(raw)}
    assert "sample_spec" not in records
    assert records["gpt-5.1-codex"]["inputCostPerMillion"] == pytest.approx(1.25)
    assert records["gpt-5.1-codex"]["outputCostPerMillion"] == pytest.approx(10.0)
    assert records["gpt-5.1-codex"]["cacheReadCostPerMillion"] == pytest.approx(0.125)
    assert "some-embedding" not in records


def test_records_from_unknown_source_raises():
    with pytest.raises(ValueError):
        pricing.records_from("no-such-source", {})


# ---------------------------------------------------------------- sync（离网）


def test_sync_modelsdev_writes_user_cache(isolated, monkeypatch):
    monkeypatch.setattr(pricing, "_urlopen", fake_urlopen_factory(MODELSDEV_SAMPLE))
    result = pricing.sync("models.dev")
    assert result["source"] == "models.dev"
    assert result["path"] == str(isolated["cache_file"])
    assert result["models"] == len(pricing.records_from_modelsdev(MODELSDEV_SAMPLE))

    raw = json.loads(isolated["cache_file"].read_text(encoding="utf-8"))
    assert raw["source"] == "models.dev" and raw["updated"]
    assert {"modelId", "inputCostPerMillion", "cacheReadCostPerMillion",
            "outputCostPerMillion"}.issubset(raw["models"][0])

    # 拉取后 load_pricing 就能读到缓存（与内置表合并）
    table = pricing.load_pricing()
    assert "gpt-5.6-sol" in table
    assert pricing.source_info()["source"] == "builtin+user-cache"


def test_sync_litellm_writes_user_cache(isolated, monkeypatch):
    monkeypatch.setattr(pricing, "_urlopen", fake_urlopen_factory({
        "gpt-5.1-codex": {"input_cost_per_token": 1.25e-06, "output_cost_per_token": 1e-05},
    }))
    result = pricing.sync("litellm", timeout=1.0)
    assert result["source"] == "litellm" and result["models"] == 1
    table = pricing.load_pricing()
    assert pricing.model_cost(table, "gpt-5.1-codex", 1_000_000, 0, 1_000_000) == pytest.approx(10.0 + 1.25)


def test_sync_does_not_write_cache_on_failure(isolated, monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.URLError("network down")
    monkeypatch.setattr(pricing, "_urlopen", boom)
    with pytest.raises(urllib.error.URLError):
        pricing.sync("models.dev")
    assert not isolated["cache_file"].exists()

    monkeypatch.setattr(pricing, "_urlopen", fake_urlopen_factory("not json at all"))
    with pytest.raises(ValueError):
        pricing.sync("models.dev")

    monkeypatch.setattr(pricing, "_urlopen", fake_urlopen_factory({"openai": {"models": {}}}))
    with pytest.raises(RuntimeError):
        pricing.sync("models.dev")

    with pytest.raises(ValueError):
        pricing.sync("unknown-source")


def test_sync_requires_valid_source(isolated):
    with pytest.raises(ValueError):
        pricing.sync("litellm2")


# ---------------------------------------------------------------- 构建脚本（离网）


def test_tools_sync_pricing_offline(tmp_path):
    """tools/sync_pricing.py 用本地快照重建内置表，产物可被 load_pricing 读取。"""
    snapshot = tmp_path / "modelsdev.json"
    snapshot.write_text(json.dumps(MODELSDEV_SAMPLE), encoding="utf-8")
    out = tmp_path / "out" / "pricing.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sync_pricing.py"),
         "--source", "models.dev", "--input", str(snapshot), "--out", str(out),
         "--updated", "2026-09-13T00:00:00+00:00"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["updated"] == "2026-09-13T00:00:00+00:00"
    assert any(r["modelId"] == "gpt-5.6-sol" for r in raw["models"])

    table = pricing.load_pricing(str(out))
    assert pricing.model_cost(table, "gpt-5.6-sol", 1_000_000, 0, 0) == pytest.approx(4.0)


def test_tools_sync_pricing_dry_run_and_bad_input(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sync_pricing.py"),
         "--input", str(tmp_path / "missing.json"), "--dry-run"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 2
    assert "读取定价渠道失败" in proc.stderr


# ---------------------------------------------------------------- 别名映射


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_alias_maps_assumed_label(isolated):
    """无公开价的标签 codex-auto-review 按映射表计价，并在明细里标 assumed/priced_as。"""
    table = {"gpt-5.5": price(5, 30, 0.5)}
    detail = pricing.model_cost_detail(table, "codex-auto-review", 1_000_000, 0, 0)
    assert detail["matched"] == "gpt-5.5"
    assert detail["priced_as"] == "gpt-5.5" and detail["assumed"] is True
    assert detail["cost_usd"] == pytest.approx(5.0)
    assert pricing.lookup(table, "codex-auto-review")["inputCostPerMillion"] == 5
    # 未命中映射/定价的模型仍是 None
    assert pricing.model_cost(table, "totally-unknown", 1_000_000, 0, 0) is None


def test_alias_target_without_price_stays_unpriced(isolated, tmp_path, monkeypatch):
    """映射目标本身无价 → 仍返回 None（标 *），不静默算出一个价。"""
    aliases = _write_json(tmp_path / "aliases.json", {
        "aliases": {"mystery-model": {"model": "not-in-table", "assumed": True}}})
    monkeypatch.setenv("CODEX_USAGE_ALIASES_FILE", str(aliases))
    pricing.load_aliases.cache_clear()
    table = {"gpt-5.5": price(5, 30, 0.5)}
    assert pricing.model_cost(table, "mystery-model", 1_000_000, 0, 0) is None
    assert pricing.model_cost_detail(table, "mystery-model", 1_000_000, 0, 0) is None


def test_alias_file_broken_falls_back_safely(isolated, tmp_path, monkeypatch):
    """映射文件损坏 → 空表（不崩），精确/归一化匹配照常。"""
    broken = tmp_path / "broken-aliases.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("CODEX_USAGE_ALIASES_FILE", str(broken))
    pricing.load_aliases.cache_clear()
    assert pricing.load_aliases() == {}
    table = {"gpt-5.6-sol": price(4, 20, 0.4)}
    assert pricing.model_cost(table, "gpt-5.6-sol", 1_000_000, 0, 0) == pytest.approx(4.0)
    assert pricing.model_cost(table, "codex-auto-review", 1_000_000, 0, 0) is None


def test_alias_does_not_override_table_entry(isolated):
    """表里显式写了同名价（用户自定义）→ 优先于假设映射，且不标 assumed。"""
    table = {"codex-auto-review": price(1, 2, 0.1), "gpt-5.5": price(5, 30, 0.5)}
    detail = pricing.model_cost_detail(table, "codex-auto-review", 1_000_000, 0, 0)
    assert detail["cost_usd"] == pytest.approx(1.0)
    assert detail["matched"] == "codex-auto-review"
    assert "priced_as" not in detail


def test_alias_key_present_in_loaded_table(isolated):
    """别名 key 注入生效：unknown_models() 不会把已计价标签误报为无价。"""
    table = pricing.load_pricing()
    assert "codex-auto-review" in table
    assert "gpt-reserve" not in table            # 不映射：保持无价


def test_aliases_info_exposes_version_and_not_mapped(isolated):
    info = pricing.aliases_info()
    assert info["version"]
    assert info["aliases"]["codex-auto-review"]["model"] == "gpt-5.5"
    assert "gpt-reserve" in info["not_mapped"]


# ---------------------------------------------------------------- 档位（priority/Fast）价


def test_tier_priority_uses_fast_price():
    table = {"gpt-5.6-sol": price(4, 20, 0.4)}
    assert pricing.model_cost(table, "gpt-5.6-sol", 1_000_000, 0, 1_000_000) == pytest.approx(24.0)
    assert pricing.model_cost(table, "gpt-5.6-sol", 1_000_000, 0, 1_000_000,
                              tier="priority") == pytest.approx(48.0)
    detail = pricing.model_cost_detail(table, "gpt-5.6-sol", 0, 0, 1_000_000, tier="fast")
    assert detail["tier"] == "priority"                  # fast ≡ priority
    assert detail["tier_priced"] is True
    assert detail["tier_confidence"] == "official"
    assert detail["standard_cost_usd"] == pytest.approx(20.0)


def test_tier_multiplier_is_per_model_not_blanket():
    """5.5 是官方 2.5×，不能统一按 2× 少算。"""
    table = {"gpt-5.5": price(5, 30, 0.5), "gpt-6-astra": price(10, 50, 1)}
    assert pricing.tier_multiplier(table, "gpt-5.5", "priority") == pytest.approx(2.5)
    assert pricing.tier_multiplier(table, "gpt-6-astra", "priority") == pytest.approx(2.0)
    assert pricing.model_cost(table, "gpt-5.5", 1_000_000, 0, 0,
                              tier="priority") == pytest.approx(12.5)


def test_tier_unknown_or_unpriced_falls_back_to_standard():
    table = {"gpt-5-codex": price(1.25, 10, 0.125), "gpt-5.6-sol": price(4, 20, 0.4),
             "gpt-5.5": price(5, 30, 0.5)}
    weird = pricing.model_cost_detail(table, "gpt-5.6-sol", 1_000_000, 0, 0, tier="weird-tier")
    assert weird["tier"] == "standard" and weird["cost_usd"] == pytest.approx(4.0)
    # 官方没有 Fast 行的模型：保持标准价并标 tier_priced=False
    noprice = pricing.model_cost_detail(table, "gpt-5-codex", 1_000_000, 0, 0, tier="priority")
    assert noprice["tier_priced"] is False and noprice["cost_usd"] == pytest.approx(1.25)
    # 别名映射后按目标模型取档位价（codex-auto-review → gpt-5.5 的 2.5×）
    assert pricing.model_cost(table, "codex-auto-review", 1_000_000, 0, 0,
                              tier="priority") == pytest.approx(12.5)


def test_tier_flex_is_half_of_standard():
    table = {"gpt-5.6-luna": price(0.2, 1.2, 0.02)}
    standard = pricing.model_cost(table, "gpt-5.6-luna", 1_000_000, 0, 1_000_000)
    flex = pricing.model_cost(table, "gpt-5.6-luna", 1_000_000, 0, 1_000_000, tier="flex")
    assert flex == pytest.approx(standard / 2)
    assert pricing.model_cost_detail(table, "gpt-5.6-luna", 0, 0, 1_000_000,
                                     tier="flex")["tier"] == "flex"


def test_tier_unknown_uses_config_toml(isolated, tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5.6-sol"\nservice_tier = "priority"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_USAGE_CODEX_CONFIG", str(config))
    pricing.default_service_tier.cache_clear()
    assert pricing.default_service_tier() == "priority"
    assert pricing.resolve_tier("unknown") == "priority"
    assert pricing.resolve_tier(None) == "priority"
    assert pricing.resolve_tier("unknown", config_tier="standard") == "standard"
    assert pricing.resolve_tier("fast") == "priority"

    monkeypatch.setenv("CODEX_USAGE_CODEX_CONFIG", str(tmp_path / "missing.toml"))
    pricing.default_service_tier.cache_clear()
    assert pricing.default_service_tier() == "default"
    assert pricing.resolve_tier("unknown") == "standard"


def test_tier_data_file_broken_falls_back_to_standard(isolated, tmp_path, monkeypatch):
    broken = tmp_path / "tiers.json"
    broken.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CODEX_USAGE_TIER_PRICING_FILE", str(broken))
    pricing.load_tier_pricing.cache_clear()
    data = pricing.load_tier_pricing()
    assert data["priority"] == {} and data["multipliers"] == {}
    table = {"gpt-5.6-sol": price(4, 20, 0.4)}
    detail = pricing.model_cost_detail(table, "gpt-5.6-sol", 1_000_000, 0, 0, tier="priority")
    assert detail["tier_priced"] is False and detail["cost_usd"] == pytest.approx(4.0)


def test_builtin_tier_table_matches_official_rates(isolated):
    """内置档位表与官方 Fast 表一致：5.5 = 2.5×，5.6 系/Astra/5.4 = 2×。"""
    multipliers = pricing.load_tier_pricing()["multipliers"]
    assert multipliers["gpt-5.5"] == pytest.approx(2.5)
    for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra", "gpt-5.4"):
        assert multipliers[model] == pytest.approx(2.0)
    table = pricing.load_pricing()
    # 5.5 priority: 12.5 in + 75 out，而不是“统一 2×”的 10 + 60
    assert pricing.model_cost(table, "gpt-5.5", 1_000_000, 0, 1_000_000,
                              tier="priority") == pytest.approx(87.5)


def test_tier_records_from_litellm_parses_confidence_and_multipliers():
    raw = {
        "gpt-5.6-sol": {"input_cost_per_token": 4e-6, "output_cost_per_token": 2e-5,
                        "cache_read_input_token_cost": 4e-7,
                        "input_cost_per_token_priority": 8e-6,
                        "output_cost_per_token_priority": 4e-5,
                        "cache_read_input_token_cost_priority": 8e-7},
        "gpt-5.3-codex": {"input_cost_per_token": 1.75e-6, "output_cost_per_token": 1.4e-5,
                          "input_cost_per_token_priority": 3.5e-6,
                          "output_cost_per_token_priority": 2.8e-5},
        "meta/some-model": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6,
                            "input_cost_per_token_priority": 2e-6,
                            "output_cost_per_token_priority": 4e-6},
        "gpt-5-codex": {"input_cost_per_token": 1.25e-6, "output_cost_per_token": 1e-5},
    }
    rows = pricing.tier_records_from_litellm(raw)
    priority = {r["modelId"]: r for r in rows["priority"]}
    assert set(priority) == {"gpt-5.6-sol", "gpt-5.3-codex"}      # 带 provider 前缀的不收
    assert priority["gpt-5.6-sol"]["confidence"] == "official"
    assert priority["gpt-5.6-sol"]["inputCostPerMillion"] == pytest.approx(8.0)
    assert priority["gpt-5.3-codex"]["confidence"] == "litellm"   # 官方无 Fast 行 → 低置信
    assert rows["multipliers"]["gpt-5.6-sol"] == pytest.approx(2.0)
    assert "gpt-5-codex" not in rows["multipliers"]                # 无 priority 价


def test_cost_for_tiered_matches_whole_model_cost(isolated, tmp_path, monkeypatch):
    """T6 不变式交叉校验：tiers 逐分量求和 == models 时，分档计价与整块计价一致。"""
    monkeypatch.setenv("CODEX_USAGE_CODEX_CONFIG", str(tmp_path / "missing.toml"))
    pricing.default_service_tier.cache_clear()
    table = {"gpt-5.6-sol": price(4, 20, 0.4), "gpt-6-astra": price(10, 50, 1)}
    models = {"gpt-5.6-sol": [1_000_000, 2_000_000, 500_000, 0, 3],
              "gpt-6-astra": [3_000_000, 1_000_000, 200_000, 0, 2]}
    tiers = {
        "gpt-5.6-sol": {"default": [600_000, 1_200_000, 300_000, 0, 2],
                        "unknown": [400_000, 800_000, 200_000, 0, 1]},
        "gpt-6-astra": {"default": [3_000_000, 1_000_000, 200_000, 0, 2]},
    }
    for model, slots in tiers.items():                    # 逐档求和 == 整块（T6 保证）
        for i in range(3):
            assert sum(slot[i] for slot in slots.values()) == models[model][i]
    summary = pricing.cost_for_tiered(tiers, table)
    assert summary["all_priced"] is True
    whole = sum(pricing.model_cost(table, m, v[0] - v[1], v[1], v[2])
                for m, v in models.items())
    assert summary["cost_usd"] == pytest.approx(whole)


def test_cost_for_tiered_adds_priority_premium():
    table = {"gpt-5.6-sol": price(4, 20, 0.4)}
    summary = pricing.cost_for_tiered({
        "gpt-5.6-sol": {"default": [1_000_000, 0, 0, 0, 1],
                        "priority": [1_000_000, 0, 0, 0, 1]}}, table)
    assert summary["cost_usd"] == pytest.approx(4.0 + 8.0)
    assert summary["models"]["gpt-5.6-sol"]["tiers"]["priority"]["tier"] == "priority"
    assert summary["models"]["gpt-5.6-sol"]["tiers"]["default"]["cost_usd"] == pytest.approx(4.0)
