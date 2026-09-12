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
