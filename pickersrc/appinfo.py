# -*- coding: utf-8 -*-
"""程序与作者的**单一定义处**（与课题组的 SHKit / SHSynth / GRACE Downloader 一家）。

界面「关于」对话框、`--version` 输出、窗口标题都从这里取，避免同一个邮箱
在三处写得不一样。

资源文件（图标、公众号二维码、README）放在包外的 `resources/` 与项目根目录，
冻结（PyInstaller）后在 `_internal/` 下 —— 两种情形都找得到，找不到就返回 None
（界面给"该把文件放哪儿"的提示，而不是崩）。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

__all__ = [
    "APP_NAME", "APP_NAME_CN", "APP_TAGLINE",
    "AUTHOR_NAME_CN", "AUTHOR_NAME_EN", "AUTHOR_EMAIL", "AUTHOR_PHONE",
    "AUTHOR_AFFILIATION_CN", "AUTHOR_AFFILIATION_EN", "AUTHOR_PUBLISHER",
    "WECHAT_ACCOUNT", "WECHAT_ACCOUNT_EN", "WECHAT_QR_FILENAME",
    "ICON_FILENAME", "ICON_PNG_FILENAME", "README_FILENAME", "GUIDE_HTML_NAME",
    "LICENSE_FILENAME", "NOTICE_FILENAME", "LICENSE_YEAR",
    "resource_dirs", "resource_path", "icon_path", "qr_image_path",
    "readme_path", "guide_html_path", "about_text", "version",
    "license_path", "notice_path", "copyright_line",
    "config_dir", "config_probe", "config_dir_is_install_dir",
    "reset_config_cache", "settings_path", "presets_path",
    "legacy_config_dirs", "migrate_legacy_config", "CONFIG_DIRNAME",
]

APP_NAME = "CG5Picker"
APP_NAME_CN = "CG5 数据挑选"
APP_TAGLINE = ("从 CG-5 原始手簿里按日期 / Survey / 条件挑出可用观测，"
               "看图形确认，再按原始格式导出 xlsx")

#: 版权年与版权行（**版权声明只有一个出处**，界面/说明书/许可文件都引用它）
LICENSE_YEAR = "2026"
LICENSE_FILENAME = "LICENSE.txt"
NOTICE_FILENAME = "NOTICE.txt"

AUTHOR_NAME_CN = "彭桢燃"
AUTHOR_NAME_EN = "Zhenran Peng"
AUTHOR_EMAIL = "zhenran.peng@cug.edu.cn"
AUTHOR_PHONE = "15927402265"
AUTHOR_AFFILIATION_CN = "中国地质大学(武汉)"
AUTHOR_AFFILIATION_EN = "China University of Geosciences (Wuhan)"

#: 安装程序 / 快捷方式里的发行者字段
AUTHOR_PUBLISHER = f"{AUTHOR_NAME_CN} {AUTHOR_NAME_EN}  ({AUTHOR_AFFILIATION_EN})"

WECHAT_ACCOUNT = "地球重力与人类生活"
WECHAT_ACCOUNT_EN = "TVGG"
WECHAT_QR_FILENAME = "地球重力与人类生活TVGG.jpg"

ICON_FILENAME = "cg5picker.ico"
ICON_PNG_FILENAME = "cg5picker_256.png"
README_FILENAME = "README.md"
GUIDE_HTML_NAME = "使用说明.html"
GUIDE_IMG_DIR = "使用说明_img"


def version() -> str:
    from . import __version__
    return str(__version__)


def _app_dir() -> Path:
    """程序所在目录（冻结版是 exe 所在目录，源码运行时是 CG5Picker/ 项目根）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dirs() -> list[Path]:
    """按优先级列出可能放资源文件的目录（每次调用重算，便于冻结/源码两种情形）。"""
    app = _app_dir()
    cands = [app / "docs", app / "_internal" / "docs",
             app / "resources", app / "_internal" / "resources",
             app / "licenses", app / "_internal" / "licenses", app,
             Path(__file__).resolve().parent / "docs",
             Path(__file__).resolve().parent / "resources"]
    out: list[Path] = []
    for c in cands:
        c = c.resolve()
        if c not in out:
            out.append(c)
    return out


def resource_path(filename: str) -> Path | None:
    for d in resource_dirs():
        p = d / filename
        if p.exists():
            return p
    return None


def icon_path() -> Path | None:
    """窗口/任务栏图标（.ico 优先，找不到退回 .png）。"""
    return (resource_path(ICON_FILENAME) or resource_path(ICON_PNG_FILENAME)
            or resource_path("icon.ico"))


def qr_image_path() -> Path | None:
    """课题组公众号二维码（随包提供）。"""
    return resource_path(WECHAT_QR_FILENAME)


def readme_path() -> Path | None:
    """随包的 README（开发者向的完整说明；界面里主推 HTML 使用说明）。"""
    return resource_path(README_FILENAME)


def guide_html_path() -> Path | None:
    """HTML 使用说明（用户向；界面里用窗口预览，也可以丢给浏览器）。"""
    return resource_path(GUIDE_HTML_NAME)


# ---------------------------------------------------------------- 许可声明
def license_path() -> Path | None:
    """本软件自身代码的许可全文（MIT）。"""
    return resource_path(LICENSE_FILENAME)


def notice_path() -> Path | None:
    """第三方组件声明（PySide6/Qt LGPLv3、matplotlib、NumPy、openpyxl…）。"""
    return resource_path(NOTICE_FILENAME)


def notice_extra_paths() -> list[Path]:
    """许可文本目录里除 NOTICE 之外的文件（LGPL-3.0 / GPL-3.0 …）。"""
    out: list[Path] = []
    for d in resource_dirs():
        p = d / "licenses"
        if p.is_dir():
            for f in sorted(p.glob("*.txt")):
                if f.name != NOTICE_FILENAME:
                    out.append(f)
            if out:
                break
    return out


def copyright_line() -> str:
    """版权行（界面、说明书、许可文件用同一句）。"""
    return (f"Copyright (c) {LICENSE_YEAR} {AUTHOR_NAME_CN}"
            f"({AUTHOR_NAME_EN}) <{AUTHOR_EMAIL}>")


# ==========================================================================
# 配置目录：**放在软件安装目录下**（用户口径："这个还是放到软件安装目录吧，
# 不要放 C 盘系统里"）。装在 C:\Program Files 这类**不可写**目录时，
# 自动退到 %LOCALAPPDATA%\CG5Picker（与 SHKit 的缓存退路同一套路）。
# ==========================================================================
CONFIG_DIRNAME = "config"
_SETTINGS_NAME = "settings.json"
_PRESETS_NAME = "presets.json"

_config_cache: "tuple[Path, bool] | None" = None


def config_dir() -> Path:
    """配置目录（安装目录下的 `config/`）。

    ★ 环境变量 `CG5PICKER_CONFIG_DIR` 可以**改到别处** —— 给自检、打包冒烟、
      绿色/U 盘版用：那些场景下不该往真正的安装目录里写"界面习惯"
      （踩过：自检与 `--smoke` 的离屏窗口把 `window/maximized=false` 写进了
      发行包，用户一打开就不最大化了）。
    """
    env = os.environ.get("CG5PICKER_CONFIG_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return _app_dir() / CONFIG_DIRNAME


def _dir_writable(d: Path) -> bool:
    """真写一个探针文件再删掉 —— 比 `os.access` 靠谱（Windows 上它不认 ACL）。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".cg5_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def config_probe() -> "tuple[Path, bool]":
    """→ `(配置目录, 是否用的安装目录)`（结果缓存；`reset_config_cache()` 可清）。"""
    global _config_cache
    if _config_cache is None:
        d = config_dir()
        if _dir_writable(d):
            _config_cache = (d, True)
        else:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            _config_cache = (Path(base) / APP_NAME, False)
    return _config_cache


def reset_config_cache() -> None:
    """清掉缓存（自检里换目录 / 换环境后要重算）。"""
    global _config_cache
    _config_cache = None


def config_dir_is_install_dir() -> bool:
    return bool(config_probe()[1])


def settings_path() -> Path:
    return config_probe()[0] / _SETTINGS_NAME


def presets_path() -> Path:
    return config_probe()[0] / _PRESETS_NAME


def legacy_config_dirs() -> list[Path]:
    """旧版本/旧决定把配置放在这些地方 —— 只用于**一次性搬家**。"""
    out: list[Path] = []
    for env in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / APP_NAME
            if p not in out:
                out.append(p)
    return out


def migrate_legacy_config(target_dir: Path) -> list[str]:
    """把旧位置（`%APPDATA%\\CG5Picker`）里的配置**搬到新位置**（目标已存在就不动）。

    返回搬过来的文件名列表（界面/日志可以说一句"配置已搬到安装目录"）。
    """
    moved: list[str] = []
    for name in (_SETTINGS_NAME, _PRESETS_NAME):
        dst = target_dir / name
        try:
            if dst.exists():
                continue
        except OSError:
            continue
        for old in legacy_config_dirs():
            src = old / name
            try:
                if not src.exists() or src.resolve() == dst.resolve():
                    continue
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                moved.append(name)
            except OSError:
                pass
            break
    return moved


def about_text() -> str:
    """「关于」对话框的纯文字版本（命令行 `--version` 也用）。"""
    return (
        f"{APP_NAME} {version()} —— {APP_NAME_CN}\n"
        f"{APP_TAGLINE}\n\n"
        f"作者    : {AUTHOR_NAME_CN}({AUTHOR_NAME_EN})\n"
        f"单位    : {AUTHOR_AFFILIATION_CN} / {AUTHOR_AFFILIATION_EN}\n"
        f"邮箱    : {AUTHOR_EMAIL}\n"
        f"电话    : {AUTHOR_PHONE}\n"
        f"公众号  : {WECHAT_ACCOUNT}({WECHAT_ACCOUNT_EN})\n\n"
        "范围    : 只处理 CG-5 手簿；日期与 Survey 两条线取交集；"
        "条件栈按 首要/或/且 分组判定；互差按滑动窗口判定、"
        "「最终取值」按观测轮次各留一条\n"
        f"版权    : {copyright_line()}\n"
        "许可    : 本软件代码 MIT（全文见 LICENSE.txt）；"
        "界面 PySide6 / Qt（LGPLv3，动态链接、未修改）；"
        "绘图 matplotlib（PSF/BSD 风格）；数值 NumPy（BSD-3）；"
        "xlsx 读写 openpyxl（MIT）—— 第三方声明见 licenses/NOTICE.txt\n"
        "用途    : 仅用于科研与教学\n"
    )
