"""
shard_ini.py — ANSI(cp1252) INI 读写
规则：
  - 所有值用双引号包裹
  - 值内部双引号转义为两个双引号
  - 段名 [section]
  - 编码 cp1252 (ANSI)
"""
from shard_const import INI_ENCODING
from shard_utils import ansi_escape, ansi_unescape


class ShardINI:
    def __init__(self):
        self.sections = {}
        self._order = []

    def set(self, section: str, key: str, value) -> None:
        if section not in self.sections:
            self.sections[section] = {}
            self._order.append(section)
        self.sections[section][key] = str(value)

    def get(self, section: str, key: str, default=None):
        return self.sections.get(section, {}).get(key, default)

    def items(self, section: str) -> dict:
        return dict(self.sections.get(section, {}))

    def dump(self, path: str) -> None:
        lines = []
        for sec in self._order:
            data = self.sections[sec]
            if not data:
                continue
            lines.append(f"[{sec}]")
            for k, v in data.items():
                escaped = ansi_escape(v)
                lines.append(f'{k}="{escaped}"')
            lines.append("")
        text = "\n".join(lines)
        with open(path, "w", encoding=INI_ENCODING, newline="\r\n") as f:
            f.write(text)

    @staticmethod
    def load(path: str) -> "ShardINI":
        obj = ShardINI()
        cur = None
        with open(path, "r", encoding=INI_ENCODING) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    cur = line[1:-1].strip()
                    if cur not in obj.sections:
                        obj.sections[cur] = {}
                        obj._order.append(cur)
                    continue
                if "=" in line and cur is not None:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    v = ansi_unescape(v)
                    obj.sections[cur][k] = v
        return obj
