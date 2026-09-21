import os
from pathlib import Path

from filelock import FileLock


def instance_lock(adapter: str, database: str) -> FileLock:
    if adapter == "wxauto":
        # 不依赖数据库路径，同一 Windows 用户的各桌面会话也保守互斥。
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
        path = base / "wechat-cs" / "desktop.lock"
    else:
        path = Path(str(Path(database).resolve()) + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(path, timeout=0)
