# -*- coding: utf-8 -*-
"""本地配置（**参数设置的记忆**）—— 放在**软件安装目录的 `config/` 下**。

用户口径："这些参数设置都要有记忆功能，配置在本地"、
"这个还是放到软件安装目录吧，不要放 C 盘系统里"。

于是：
  · 安装版 → `<安装目录>\\config\\settings.json`（与 `presets.json` 同目录）；
  · 装在 `C:\\Program Files` 这类**不可写**目录时 → 自动退到
    `%LOCALAPPDATA%\\CG5Picker\\settings.json`（写盘失败不该让界面变哑巴）；
  · 旧版本放在 `%APPDATA%\\CG5Picker` 的配置会**一次性搬过来**（`migrate_legacy_config`）。

设计取舍：
  · **一个文件、一层键值**（`"export/survey_header": true` 这种扁键），
    读起来一眼知道是哪儿的设置，加新键不用改结构、老文件也不会读坏；
  · 任何一步失败都**不抛到界面上**：读不了就用默认值、写不了就只留内存态
    （`self.error` 里记原因，界面的"关于"里能看到配置文件路径）；
  · 写盘用**临时文件 + 替换**，中途崩不会留下半截 JSON（预设文件踩过这个坑）；
  · 和条件参数组合（`presets.json`）分开放：那个是"用户资产"，
    这个是"界面习惯"，删掉不该丢条件。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import appinfo

__all__ = ["Settings", "default_path", "KEY_EXPORT_SURVEY_HEADER"]

#: 导出对话框的默认值：**默认勾选"附 Survey 文件头"**（用户口径）
KEY_EXPORT_SURVEY_HEADER = "export/survey_header"


def default_path() -> Path:
    """配置文件路径：**安装目录的 `config/settings.json`**（不可写才退到用户目录）。"""
    return appinfo.settings_path()


#: 出厂默认（文件里没有该键时用它）
DEFAULTS: dict[str, Any] = {
    KEY_EXPORT_SURVEY_HEADER: True,      # ★ 导出默认附 Survey 文件头
    "export/reason": False,
    "export/mode": "verbatim",
    "export/which": "keep",
    "export/dir": "",
    "view/show_all": True,
    "view/only_manual": False,
    "plot/kind": "time",
    "columns/order": [],
    "window/geometry": "",
    "window/state": "",
    "window/split": [],
    "window/maximized": True,
    "paths/last_dir": "",
    "source/follow": True,
    "preset/last": "",
}


class Settings:
    """扁键的本地配置：`get / set / update / flush`。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self._explicit = path is not None          # 显式路径（自检用）→ 不做旧配置搬家
        self.path = Path(path) if path else default_path()
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.error = ""
        self.migrated: list[str] = []
        self._dirty = False
        self.load()

    # ---------------------------------------------------------------- 读写
    def load(self) -> None:
        self.error = ""
        if not self.path.exists() and not self._explicit:
            # 旧版本把配置放在 %APPDATA%\CG5Picker —— 第一次用新版本时搬过来
            try:
                self.migrated = appinfo.migrate_legacy_config(self.path.parent)
            except Exception:                          # noqa: BLE001
                self.migrated = []
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(k, str):
                    self.data[k] = v

    def save(self) -> bool:
        """落盘；失败只记 `self.error`，不抛。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            self.error = ""
            self._dirty = False
            return True
        except OSError as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    # ---------------------------------------------------------------- 取值
    def get(self, key: str, default: Any = None) -> Any:
        if default is None:
            default = DEFAULTS.get(key)
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if self.data.get(key) != value:
            self.data[key] = value
            self._dirty = True

    def update(self, **kw: Any) -> None:
        for k, v in kw.items():
            self.set(k.replace("__", "/"), v)

    def flush(self) -> bool:
        """有改动才写盘（关窗口时调用，避免每动一下就 IO）。"""
        if not self._dirty:
            return True
        return self.save()

    # ---------------------------------------------------------------- 便捷
    def describe_location(self) -> str:
        """给界面用的一句话：配置文件在哪、是不是用的安装目录。"""
        where = ("软件安装目录" if appinfo.config_dir_is_install_dir()
                 else "用户目录（安装目录不可写，自动退到这里）")
        return f"{self.path}　（{where}）"

    def export_options(self) -> dict[str, Any]:
        """导出对话框的初值（含**默认附 Survey 文件头**）。"""
        return {
            "mode": str(self.get("export/mode")),
            "which": str(self.get("export/which")),
            "reason": bool(self.get("export/reason")),
            "survey_header": bool(self.get(KEY_EXPORT_SURVEY_HEADER, True)),
        }

    def remember_export(self, *, mode: str, which: str, reason: bool,
                        survey_header: bool, directory: str = "") -> None:
        self.set("export/mode", str(mode))
        self.set("export/which", str(which))
        self.set("export/reason", bool(reason))
        self.set(KEY_EXPORT_SURVEY_HEADER, bool(survey_header))
        if directory:
            self.set("export/dir", str(directory))
