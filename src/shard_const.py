"""
shard_const.py — shard 工具常量集中定义
规范 v1 对齐
"""
from enum import IntEnum

# ===== 包元信息 =====
PACKAGE_FORMAT = "shard"
PACKAGE_VERSION = "1"
PACKAGE_TOOL = "shard/1.0.0"
PACKAGE_COMPRESSION = "store"

# ===== 段名 / 字段名 =====
SEC_PACKAGE = "package"
SEC_CHUNK = "chunk"
SEC_VERIFY = "verify"

# ===== 分片命名后缀 =====
CHUNK_NUM_SUFFIX = ".shard"   # eg.exe.shard1
CHUNK_LAST_NAME = "shardm"    # eg.exe.shardm

# ===== 默认值 =====
DEFAULT_CHUNK_SIZE = 1 * 1024 * 1024   # 1MB
DEFAULT_TMP_DIR = "tmp"
DEFAULT_OUTPUT_MULTI = "shards"

# ===== 编码 =====
INI_ENCODING = "cp1252"   # ANSI

# ===== 退出码 =====
class ExitCode(IntEnum):
    OK = 0               # 全通过
    HAS_FAIL = 1         # 有 fail 但完成
    USER_TERMINATED = 2  # 被用户终止
    ARG_ERR = 3          # 参数错误
    FILE_NOT_FOUND = 4   # 文件不存在
