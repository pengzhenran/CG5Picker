# 打包环境与步骤（CG5Picker）

> 这份是**给打包的人**看的（用户拿到的是安装包，不需要看这个）。

## 1. 极简环境（**专用、不蹭别的环境**）

打包**必须用一个只装这几样的干净环境**，不要蹭 `..\GravProc\.venv` 或系统 Python：
那边多出来的 pandas / scipy / 测试框架会被 PyInstaller 的钩子拖进包里
（目录包从 **152 MB 涨到 260 MB+**，而且每次构建结果不可复现）。

```powershell
uv venv --python 3.12 D:\CG5Picker_build\venv
uv pip install --python D:\CG5Picker_build\venv\Scripts\python.exe `
    -r packaging\requirements-build.txt
```

`packaging/requirements-build.txt` 里就五行（按实测钉住版本）：

```
PySide6-Essentials==6.11.2      # ⚠️ 只装 Essentials，完整版会带 GPL-only 的 Qt Charts
matplotlib==3.11.2
numpy==2.5.3
openpyxl==3.1.5
pyinstaller==6.22.3             # 打包工具本身不随发行包分发
```

* 用 **uv** 而不是 conda/系统 Python：秒级建好、默认不带 pip 之外的框架；
* NumPy 走 **PyPI(OpenBLAS)**，别用 Anaconda 的 MKL 版（目录包会被撑到 1 GB 级）；
* **pandas / scipy 一个都不装**（本工具不用；matplotlib 的钩子会去找它们）。

**`build_installer.ps1` 默认就这么干**：`-BuildRoot` 下的 `venv\` 不存在就自动用 uv 建好并装
依赖；想用别的解释器加 `-Python <路径>`，想跳过创建加 `-SkipFreshEnv`。
脚本还会打印一行核对：`构建环境很精简（无 pandas / scipy / pytest）`，或警告你包会偏大。

| 组件 | 版本（本次实测） | 说明 |
|---|---|---|
| Python | 3.12.13（uv 建的 `D:\CG5Picker_build\venv`） | 专用极简环境 |
| PySide6-Essentials | 6.11.2 | 界面（LGPLv3，onedir 动态链接） |
| matplotlib | 3.11.2 | 绘图 |
| numpy | 2.5.3 | 数值 |
| openpyxl | 3.1.5 | xlsx 导出 |
| PyInstaller | 6.22.3 | 打包（不带进发行包） |
| Inno Setup | 6.x | 出安装包；`winget install -e --id JRSoftware.InnoSetup` |

Inno Setup 的官方安装包**不带简体中文向导语言文件**。要中文向导：
把 `ChineseSimplified.isl` 放到 `packaging\languages\`，构建脚本会自动注入到
`<Inno Setup>\Languages\` 并加上 `/DHaveChinese=1`；没有就退回英文向导（不影响功能）。

## 2. 一条命令

```powershell
cd CG5Picker
powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
# 可选：-BuildRoot E:\CG5_build   -SkipInstaller   -SkipMirror   -SkipFreshEnv   -Python <python.exe>
```

脚本按顺序做：

1. **镜像项目**到 `D:\CG5Picker_build\project`（默认构建根，可用 `-BuildRoot` 改）
   —— 不在 NAS/项目目录里直接构建；`config\`、`__pycache__`、`_selfcheck` 产物、`.venv`
   都**不镜像**（`config\` 是用户运行期生成的，跟着安装目录走，不能打进包）。
2. `packaging\make_version_info.py` 生成 `packaging\version_info.txt`（exe 属性里的
   版本 / 版权 / 公司 / 联系方式，取 `pickersrc.appinfo`，版权行与界面同一句）。
3. `packaging\check_licensing.py` **许可合规自查**（不通过直接中止）：代码里不能有
   GPL-only 的 Qt 模块、只 import QtCore/QtGui/QtWidgets、`LICENSE.txt` +
   `licenses/{NOTICE,LGPL-3.0,GPL-3.0}.txt` 齐全、spec 排除了 GPL-only 且用 onedir。
4. `pyinstaller packaging\cg5picker.spec` → `<构建根>\dist\CG5Picker\`（onedir）
   然后**冒烟测试** `CG5Picker.exe --version` 与 `--licenses`，并逐项检查随包数据
   （`_internal\licenses\*`、`_internal\docs\使用说明.html`、`_internal\resources\cg5picker.ico`）。
5. `CG5Picker.exe --smoke`：把界面真装配一遍，并核对
   **默认启动是否最大化**（`want_max=True`）与**冒烟有没有污染发行包配置**。
6. 找到 `ISCC.exe` 就编安装包 → `<构建根>\dist\CG5Picker_Setup_v1.0.0.exe`
   （带许可页 + 第三方声明页；Inno 装了中文语言文件就用中文向导，否则英文）。
   找不到就提示怎么装（目录包已经可用，退出码 2）。

> ISCC 的搜索顺序：`%LOCALAPPDATA%\Programs\Inno Setup 6`、`Program Files`、
> `Program Files (x86)`、各盘根目录的 `Inno Setup 6`（**本机就在 `E:\Inno Setup 6`**），
> 兜底再按盘扫两层；都不行就用 `-Iscc <ISCC.exe>` 显式指定。

## 3. 产物与退出码

```
<构建根>\dist\CG5Picker\CG5Picker.exe + _internal\     目录包（可绿色运行，实测 152 MB）
<构建根>\dist\CG5Picker_Setup_v1.0.0.exe               安装包（实测 45 MB）
```

**退出码**：`0` = 全部成功；`2` = 目录包已就绪但**没编安装包**（机器上没装 Inno Setup）；
`1` = 中途失败（脚本会打印卡在哪一步）。

脚本最后会做三项**冒烟测试**（都是真跑冻结版，不是"应该没问题"）：

| 测试 | 验什么 |
|---|---|
| `CG5Picker.exe --version` | Python 运行时 + `pickersrc` 包能导入，中文输出编码正确 |
| `CG5Picker.exe --licenses` | `licenses/NOTICE.txt` 随包且能读（含 LGPL / PySide6 声明） |
| `CG5Picker.exe --smoke` | **把界面真的装配一遍**（Qt 平台插件 + matplotlib 画布 + 条件栈），用 offscreen 平台不弹窗；顺带核对默认最大化 |

**安装包也实测过一遍**（静默装 → 跑 → 卸）：

```powershell
CG5Picker_Setup_v1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=D:\CG5Picker_test_install
#   装出来的关键文件：CG5Picker.exe、_internal\{licenses,docs,resources}、source\
#   跑起来 IsZoomed=True（**默认最大化** ✓）；配置写到安装目录 config\settings.json
D:\CG5Picker_test_install\unins000.exe /VERYSILENT   # 卸载干净
```

安装包（Inno Setup，**按用户安装**，不弹管理员）会装到
`%LOCALAPPDATA%\Programs\CG5Picker`，并带：

* **许可页**（`LICENSE.txt` = MIT 全文，必须同意才能继续）；
* **安装前信息页**（`licenses\NOTICE.txt` = 第三方组件与 LGPLv3 声明）；
* 开始菜单：`CG5 数据挑选` / `使用说明 (HTML)` / `作者信息（关于）` / `许可与第三方声明` / `卸载`；
* 可选桌面快捷方式；
* `source\` 里随包附运行代码（`pickersrc\`）+ README + LICENSE + licenses + docs + packaging。

> **为什么装在 `%LOCALAPPDATA%\Programs` 而不是 `C:\Program Files`**：本软件把
> 参数设置与条件组合存在**安装目录的 `config\`** 下（用户要求"别放 C 盘系统里"）。
> 按用户安装的目录可写，配置才能存下来；万一用户手工改到 `C:\Program Files`，
> 程序会自动退到 `%LOCALAPPDATA%\CG5Picker\`（界面「关于 → 配置文件位置」会写明）。
> **卸载会连同 `config\` 一起删掉** —— 要保留先把 `config\` 备份出去。

## 4. 踩过的坑

* **绝不用 `--onefile`**：Qt 是 LGPLv3，要求终端用户能替换该库；onefile 会把 DLL
  压进归档再解到临时目录（社区公认的 relinking 风险）。spec 里用的是 onedir（`COLLECT`）。
* **入口不能是 `main.py`/`window.py`**：PyInstaller 把入口当顶层脚本执行，
  `pickersrc` 里的相对导入会 `ImportError`。入口固定用
  `packaging\cg5picker_launcher.py`（先 `import pickersrc.*` 再调用）。
* **打包环境里若装了完整 PySide6**（带 Addons → Qt Charts 等 GPL-only 模块），
  必须在 spec 的 `excludes` 里排掉；`GPL_ONLY` 列表 + `check_licensing.py` 双保险。
* **`docs\` 与 `licenses\` 必须随包**：说明书是界面运行时读的（丢了"使用说明"就是空的），
  许可全文是 LGPLv3 的硬要求。
* 冻结版排错：先 `set CG5PICKER_CONSOLE=1` 再打包，会得到带控制台窗口的 exe，
  启动期异常就能看见。
* **`.ps1` 里写中文必须存成 UTF-8 *带 BOM***：Windows PowerShell 5.1 会把无 BOM 的
  UTF-8 当 ANSI(GBK) 读，中文字符串里的引号会被吃掉 → 整段脚本语法错误
  （实测踩过：`Say "Python：$Python"` 变成 `Say "Python锛?Python"`，脚本直接不解析）。
  本仓库的 `build_installer.ps1` 带 BOM，编辑时别把 BOM 弄丢。
* **冻结版的中文 stdout 要显式切 UTF-8**：从管道（PowerShell 抓输出）出来时默认按
  控制台码页(GBK)编码，会成乱码、让冒烟测试假失败。`cg5picker_launcher.py` 里
  `_force_utf8_stdout()` 做了 `sys.stdout.reconfigure(encoding="utf-8")`；
  构建脚本的断言也**只用 ASCII 标记**（CG5Picker / MIT / LGPL / smoke OK）。
* `pandas` / `scipy` 是 matplotlib 钩子拖进来的可选依赖，本工具用不到 ——
  spec 的 `excludes` 里排掉了（省体积）；**排掉后必须重跑 `--smoke` 验证**
  画布还能建起来。
* 杀软误报：不要用 UPX（spec 里已关）。
