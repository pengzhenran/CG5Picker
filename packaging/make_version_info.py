# -*- coding: utf-8 -*-
"""生成 PyInstaller 用的版本资源 `packaging/version_info.txt`。

版本号、作者、单位都从 `pickersrc.appinfo` 与 `pickersrc.__version__` 取，
避免"exe 属性里的版本"和代码里的版本对不上；版权行也直接引用
`appinfo.copyright_line()`（与界面、说明书、LICENSE.txt 同一句）。

    python packaging/make_version_info.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEMPLATE = """\
# UTF-8
#
# PyInstaller 版本资源 —— 决定 CG5Picker.exe 的「属性 → 详细信息」里显示什么，
# 也是用户/杀软判断"这是谁发的软件"的依据。PyInstaller 用 --version-file 读它。
#
# **本文件由 packaging/make_version_info.py 自动生成，别手改**：
#   改版本号/作者请改 pickersrc/__init__.py 与 pickersrc/appinfo.py，再重新生成。

VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers4},
    prodvers={vers4},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '080404B0',
        [StringStruct('CompanyName', '{company}'),
        StringStruct('FileDescription', '{app} —— {app_cn}'),
        StringStruct('FileVersion', '{vers4d}'),
        StringStruct('InternalName', '{app}'),
        StringStruct('LegalCopyright', '{copyright}  本软件代码 MIT 许可；界面 PySide6/Qt(LGPLv3)。'),
        StringStruct('OriginalFilename', '{app}.exe'),
        StringStruct('ProductName', '{app} {app_cn}'),
        StringStruct('ProductVersion', '{vers3}'),
        StringStruct('Comments', '{tagline}'),
        StringStruct('LegalTrademarks', 'Qt 及相关商标归 The Qt Company Ltd. 所有'),
        StringStruct('Author', '{author_cn} {author_en}'),
        StringStruct('Contact', '{email}')])
      ]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
  ]
)
"""


def main() -> int:
    import pickersrc
    from pickersrc import appinfo

    vers = pickersrc.__version__
    parts = [int(p) for p in vers.split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    f = dict(
        vers4=tuple(parts[:4]),
        vers4d=".".join(str(p) for p in parts[:4]),
        vers3=".".join(str(p) for p in parts[:3]),
        company=f"{appinfo.AUTHOR_AFFILIATION_CN} {appinfo.AUTHOR_AFFILIATION_EN}",
        app=appinfo.APP_NAME,
        app_cn=appinfo.APP_NAME_CN,
        tagline=appinfo.APP_TAGLINE,
        author_cn=appinfo.AUTHOR_NAME_CN,
        author_en=appinfo.AUTHOR_NAME_EN,
        email=appinfo.AUTHOR_EMAIL,
        copyright=appinfo.copyright_line(),
    )
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "version_info.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(TEMPLATE.format(**f))
    print(f"已生成 {out}（版本 {f['vers4d']}，作者 {f['author_cn']}，"
          f"版权 {f['copyright']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
