"""
shard_utils.py — 通用工具：哈希、大小解析、时间、路径处理
"""
import hashlib
import os
import stat
from datetime import datetime


def sha256_file(path: str, bufsize: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(bufsize)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_size(s: str) -> int:
    if s is None:
        raise ValueError("size is None")
    s = str(s).strip().upper()
    if not s:
        raise ValueError("empty size")
    units = [("KB", 1024), ("MB", 1024 * 1024), ("GB", 1024 ** 3), ("B", 1)]
    for suf, mult in units:
        if s.endswith(suf):
            num = s[: -len(suf)].strip()
            try:
                v = float(num)
            except ValueError:
                raise ValueError(f"bad size number: {num}")
            return int(v * mult)
    try:
        return int(s)
    except ValueError:
        raise ValueError(f"cannot parse size: {s}")


def fmt_size(n: int) -> str:
    n = int(n)
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.2f} KB"
    elif n < 1024 ** 3:
        return f"{n / (1024 * 1024):.2f} MB"
    else:
        return f"{n / (1024 ** 3):.2f} GB"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ansi_escape(s: str) -> str:
    return str(s).replace('"', '""')


def ansi_unescape(s: str) -> str:
    return str(s).replace('""', '"')


def get_mtime(path: str) -> float:
    return os.stat(path).st_mtime


def set_mtime(path: str, mtime: float):
    os.utime(path, (mtime, mtime))


def get_mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def set_mode(path: str, mode: int):
    try:
        os.chmod(path, mode)
    except (PermissionError, OSError):
        pass


def is_symlink(path: str) -> bool:
    return os.path.islink(path)
