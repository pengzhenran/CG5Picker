r"""筛选条件参数组合 —— **存储**与切换。

用户要求："筛选条件这一项作为存储条件参数组合的，切换后立即全部勾选条件栈里的，并生效。"

所以这里的模型是：
  · 一个**参数组合**（命名） = 一整条条件栈（每条条件含参数与勾选状态）
  · 切换组合 → 把整条栈替换进去，而且**全部勾选**（`enabled=True`）后立即生效
  · 组合可**保存 / 另存为 / 重命名 / 删除**，落在磁盘上，跨次启动还在

存储位置：**软件安装目录的 `config/presets.json`**（用户口径："放到软件安装目录吧，
不要放 C 盘系统里"；安装目录不可写时自动退到 `%LOCALAPPDATA%\CG5Picker`，
与 `settings.json` 同一个目录）。首次启动会把内置组合写入该文件，之后以文件为准。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import appinfo
from .rules import PRESETS, Cond, migrate_conds

__all__ = ["PresetStore", "Preset", "default_store_path", "RESERVED"]

#: 内置组合的键（用户另存时不允许重名覆盖）
RESERVED = tuple(PRESETS)


def default_store_path() -> Path:
    """**安装目录 `config/presets.json`**（与 settings.json 同目录）。"""
    return appinfo.presets_path()


def _builtin() -> list[dict[str, Any]]:
    """内置组合（来自 `rules.PRESETS`），条件默认**全部勾选**。"""
    out = []
    for key, p in PRESETS.items():
        conds = p["conds"]()
        for c in conds:
            c.enabled = True
        out.append({
            "name": p["cn"],
            "key": key,
            "builtin": True,
            "desc": p["desc"],
            "conds": [c.to_dict() for c in conds],
        })
    return out


class Preset:
    """一个命名的条件参数组合。"""

    def __init__(self, name: str, conds: list[Cond], *,
                 key: str = "", builtin: bool = False, desc: str = "") -> None:
        self.name = name
        self.conds = list(conds)
        self.key = key
        self.builtin = builtin
        self.desc = desc

    # 组合被切换时要求"立即全部勾选条件栈里的，并生效"
    def instantiate(self) -> list[Cond]:
        """返回**深拷贝**，且**全部 enabled**（切过来就生效）。"""
        out: list[Cond] = []
        for c in self.conds:
            d = c.to_dict()
            d["enabled"] = True
            out.append(Cond.from_dict(d))
        return out

    def same_as(self, conds: list[Cond]) -> bool:
        """当前栈与该组合是否一致（含勾选状态与**连接词**），用于提示"未保存的修改"。"""
        if len(conds) != len(self.conds):
            return False
        for a, b in zip(conds, self.conds):
            if (a.kind, a.enabled, a.link, _norm(a.params)) != (
                    b.kind, b.enabled, b.link, _norm(b.params)):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "key": self.key, "builtin": self.builtin,
                "desc": self.desc, "conds": [c.to_dict() for c in self.conds]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Preset":
        conds = []
        for cd in d.get("conds", []):
            try:
                conds.append(Cond.from_dict(cd))
            except KeyError:
                continue                       # 版本变化导致的未知条件 → 跳过
        # 老预设把「分段间隔」放在「最终取值」的参数里 → 拆成独立一条（且）
        conds = migrate_conds(conds)
        return cls(name=str(d.get("name", "未命名")), conds=conds,
                   key=str(d.get("key", "")), builtin=bool(d.get("builtin", False)),
                   desc=str(d.get("desc", "")))


def _norm(params: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in params.items():
        out[k] = round(float(v), 9) if isinstance(v, (int, float)) else v
    return out


class PresetStore:
    """条件参数组合的读写。任何一步失败都不抛到界面上，只降级为"内存态"。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self.presets: list[Preset] = []
        self.error = ""
        self.load()

    # ---------------------------------------------------------------- 读写
    def load(self) -> None:
        builtin = [Preset.from_dict(d) for d in _builtin()]
        self.presets = builtin
        self.error = ""
        if not self.path.exists():
            self.save()                        # 首次运行落地一份，方便用户看/改
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            user = [Preset.from_dict(d) for d in data.get("presets", [])
                    if not d.get("builtin")]
            if user:
                self.presets = builtin + user
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def save(self) -> bool:
        """只落盘**用户自定义**的组合；内置的每次由代码提供，便于升级。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1,
                       "presets": [p.to_dict() for p in self.presets if not p.builtin]}
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            self.error = ""
            return True
        except OSError as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    # ---------------------------------------------------------------- 查询
    def names(self) -> list[str]:
        return [p.name for p in self.presets]

    def get(self, name: str) -> Preset | None:
        for p in self.presets:
            if p.name == name:
                return p
        return None

    def index_of(self, name: str) -> int:
        for i, p in enumerate(self.presets):
            if p.name == name:
                return i
        return -1

    def user_names(self) -> list[str]:
        return [p.name for p in self.presets if not p.builtin]

    # ---------------------------------------------------------------- 修改
    def add(self, name: str, conds: list[Cond], *, desc: str = "",
            overwrite: bool = False) -> tuple[bool, str]:
        """存一个用户组合。重名（含内置名）默认拒绝，`overwrite=True` 才覆盖。"""
        name = name.strip()
        if not name:
            return False, "名称不能为空。"
        i = self.index_of(name)
        if i >= 0:
            if self.presets[i].builtin and not overwrite:
                return False, f"「{name}」是内置组合，请换个名字。"
            if not overwrite:
                return False, f"已存在同名组合「{name}」。"
            if self.presets[i].builtin:
                return False, f"「{name}」是内置组合，不能覆盖，请换个名字。"
            self.presets[i] = Preset(name, [Cond.from_dict(c.to_dict()) for c in conds],
                                     desc=desc)
        else:
            self.presets.append(
                Preset(name, [Cond.from_dict(c.to_dict()) for c in conds], desc=desc))
        ok = self.save()
        return True, ("" if ok else f"已加入列表，但写文件失败：{self.error}")

    def rename(self, old: str, new: str) -> tuple[bool, str]:
        new = new.strip()
        if not new:
            return False, "名称不能为空。"
        i = self.index_of(old)
        if i < 0:
            return False, f"没有组合「{old}」。"
        if self.presets[i].builtin:
            return False, f"「{old}」是内置组合，不能改名。"
        if new != old and self.index_of(new) >= 0:
            return False, f"已存在同名组合「{new}」。"
        self.presets[i].name = new
        ok = self.save()
        return True, ("" if ok else f"已改名，但写文件失败：{self.error}")

    def remove(self, name: str) -> tuple[bool, str]:
        i = self.index_of(name)
        if i < 0:
            return False, f"没有组合「{name}」。"
        if self.presets[i].builtin:
            return False, f"「{name}」是内置组合，不能删除。"
        del self.presets[i]
        ok = self.save()
        return True, ("" if ok else f"已删除，但写文件失败：{self.error}")
