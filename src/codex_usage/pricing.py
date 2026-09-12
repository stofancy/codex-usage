"""模型定价：加载 cc-switch 维护的 model-pricing.json，按模型折算成本。"""

import json
import os

from . import config


def load_pricing(path: str | None = None) -> dict[str, dict]:
    """加载定价表 → {modelId: {inputCostPerMillion: ...}}；文件缺失返回空表。"""
    path = path or config.pricing_file()
    try:
        d = json.load(open(path))
        return {m["modelId"]: m for m in d.get("models", [])}
    except Exception:
        return {}


def model_cost(pricing: dict[str, dict], model: str, net_in: int, cached: int, out: int) -> float | None:
    """单模型成本（USD）；无定价模型返回 None（调用方按 $0 计并标注）。"""
    p = pricing.get(model)
    if not p:
        return None
    try:
        f = lambda k: float(p.get(k) or 0)
        return (net_in * f("inputCostPerMillion") + cached * f("cacheReadCostPerMillion")
                + out * f("outputCostPerMillion")) / 1e6
    except Exception:
        return None
