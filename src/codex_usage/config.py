"""数据路径配置：默认指向本机 Codex / cc-switch 目录，可用环境变量覆盖（便于测试）。"""

import os


def sessions_dir() -> str:
    return os.environ.get("CODEX_USAGE_SESSIONS_DIR",
                          os.path.join(os.path.expanduser("~"), ".codex", "sessions"))


def archive_dir() -> str:
    return os.environ.get("CODEX_USAGE_ARCHIVE_DIR",
                          os.path.join(os.path.expanduser("~"), ".codex", "archived_sessions"))


def pricing_file() -> str:
    return os.environ.get("CODEX_USAGE_PRICING_FILE",
                          os.path.join(os.path.expanduser("~"), ".cc-switch", "model-pricing.json"))


def cache_dir() -> str:
    """用户缓存目录：sync 拉取的公开定价表写在这里（CODEX_USAGE_CACHE_DIR 可覆盖）。"""
    return os.environ.get("CODEX_USAGE_CACHE_DIR",
                          os.path.join(os.path.expanduser("~"), ".cache", "codex-usage"))


def cache_pricing_file() -> str:
    """用户缓存定价表路径（load_pricing 的第二优先级）。"""
    return os.path.join(cache_dir(), "pricing.json")
