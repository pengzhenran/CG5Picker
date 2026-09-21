# =============================================================================
#  CG5Picker —— 一键打包：PyInstaller 目录包 + Inno Setup 安装包
# =============================================================================
#  用法（在 CG5Picker\ 目录下）：
#      powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
#      powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1 -SkipInstaller
#      powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1 -BuildRoot E:\CG5_build
#
#  做四件事：
#    1) 把项目**镜像**到构建根（默认 D:\CG5Picker_build\project）—— 不在 NAS/项目目录里
#       直接构建，产物与源码分开；config\、__pycache__、_selfcheck 产物都不镜像。
#    2) 生成版本资源（packaging\make_version_info.py）并跑许可合规自查
#       （packaging\check_licensing.py，不通过就中止）。
#    3) PyInstaller 出目录包：<构建根>\dist\CG5Picker\CG5Picker.exe + _internal\，
#       然后**冒烟测试**：CG5Picker.exe --version / --licenses。
#    4) 找到 Inno Setup 的 ISCC.exe 就编译安装包：
#       <构建根>\dist\CG5Picker_Setup_v<版本>.exe（带许可页与第三方声明页）。
#       找不到就打印怎么装（winget install JRSoftware.InnoSetup）。
# =============================================================================
[CmdletBinding()]
param(
    [string]$BuildRoot = "D:\CG5Picker_build",
    [string]$Python = "",
    [string]$Iscc = "",
    [switch]$SkipInstaller,
    [switch]$SkipBuild,          # 复用已有目录包，只重编安装程序
    [switch]$SkipMirror,
    [switch]$SkipFreshEnv,
    [switch]$KeepBuild
)

$ErrorActionPreference = "Stop"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Proj = Split-Path -Parent $Here            # CG5Picker\
$ProjMirror = Join-Path $BuildRoot "project"
$Dist = Join-Path $BuildRoot "dist"

# ---------------------------------------------------------------- 1) 解释器
#   ★ 默认用**构建根下的专用极简环境**（$BuildRoot\venv，uv 建）：
#     · 不蹭 GravProc\.venv / 系统 Python —— 那里的 pandas / scipy / 测试框架会被
#       PyInstaller 的钩子拖进包里（目录包从 ~170 MB 涨到 260 MB+），也不可复现；
#     · 只装 PySide6-**Essentials**（避免 GPL-only 的 Qt Charts 混进来）。
#     已有环境就复用；用 -Python 指定别的解释器、-SkipFreshEnv 跳过创建。
$Venv = Join-Path $BuildRoot "venv"
$ReqFile = Join-Path $Here "requirements-build.txt"

if (-not $Python) {
    $VenvPy = Join-Path $Venv "Scripts\python.exe"
    if ((-not $SkipFreshEnv) -and (-not (Test-Path $VenvPy))) {
        $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
        if (-not $uv) {
            foreach ($c in @("$env:USERPROFILE\.local\bin\uv.exe",
                             "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe")) {
                if (Test-Path $c) { $uv = $c; break }
            }
        }
        if ($uv) {
            Say "建极简构建环境（uv）：$Venv"
            & $uv venv --python 3.12 $Venv
            if ($LASTEXITCODE -ne 0) { throw "uv venv 失败" }
            Say "装打包依赖（packaging\requirements-build.txt）"
            & $uv pip install --python $VenvPy -r $ReqFile
            if ($LASTEXITCODE -ne 0) { throw "uv pip install 失败" }
        } else {
            Warn "没找到 uv —— 退回 python -m venv（会慢一些，但仍只装 requirements 里那几个）"
            $base = (Get-Command python -ErrorAction SilentlyContinue).Source
            if (-not $base) { throw "既没有 uv 也没有 python，无法建构建环境" }
            & $base -m venv $Venv
            & $VenvPy -m pip install -q --upgrade pip
            & $VenvPy -m pip install -q -r $ReqFile
        }
    }
    if (Test-Path $VenvPy) {
        $Python = $VenvPy
    } else {
        $cands = @((Join-Path $Proj ".venv\Scripts\python.exe"),
                   (Join-Path (Split-Path -Parent $Proj) "GravProc\.venv\Scripts\python.exe"))
        foreach ($c in $cands) { if (Test-Path $c) { $Python = $c; break } }
        if ($Python) { Warn "没有专用构建环境，暂时用共享环境（包会偏大）：$Python" }
    }
}
if (-not $Python -or -not (Test-Path $Python)) {
    throw "找不到可用的 Python 解释器，请用 -Python <路径> 指定（需要装了 PyInstaller）。"
}
Say "Python：$Python"

$ver = & $Python -c "import PyInstaller, sys; print(PyInstaller.__version__)" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $ver) {
    throw "这个解释器里没有 PyInstaller。请先：`"$Python`" -m pip install pyinstaller"
}
Say "PyInstaller：$ver"
# 精简核对：构建环境里不该出现 pandas / scipy（会被钩子拖进包）
$fat = & $Python -c "import importlib.util as u; print(','.join(m for m in ('pandas','scipy','pytest') if u.find_spec(m)))" 2>$null
if ($fat) { Warn "构建环境里还有 $fat —— 包会偏大（spec 已 excludes，但最好用极简环境）" }
else { Say "构建环境很精简（无 pandas / scipy / pytest）" }

$AppVer = (& $Python -c "import sys; sys.path.insert(0, r'$Proj'); import pickersrc; print(pickersrc.__version__)").Trim()
Say "版本：$AppVer"

# ---------------------------------------------------------------- 2) 版本资源 + 合规自查
Say "生成版本资源（packaging\version_info.txt）"
& $Python (Join-Path $Here "make_version_info.py")
if ($LASTEXITCODE -ne 0) { throw "生成版本资源失败" }

Say "许可合规自查（packaging\check_licensing.py）"
& $Python (Join-Path $Here "check_licensing.py")
if ($LASTEXITCODE -ne 0) { throw "许可合规自查未通过 —— 先按上面的 FAIL 项修好再打包" }

# ---------------------------------------------------------------- 3) 镜像项目
if (-not $SkipMirror) {
    if (Test-Path $ProjMirror) { Remove-Item $ProjMirror -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $ProjMirror | Out-Null
    Say "镜像项目到 $ProjMirror"
    $exclDirs = @(".venv", "__pycache__", "_selfcheck", "build", "dist", "config", ".git")
    Get-ChildItem $Proj -Directory | Where-Object { $exclDirs -notcontains $_.Name } | ForEach-Object {
        Copy-Item $_.FullName -Destination (Join-Path $ProjMirror $_.Name) -Recurse -Force
    }
    Get-ChildItem $Proj -File | Where-Object { $_.Extension -ne ".xlsx" } | ForEach-Object {
        Copy-Item $_.FullName -Destination $ProjMirror -Force
    }
    # 清掉镜像里的 pycache（构建包更小、也不带开发痕迹）
    Get-ChildItem $ProjMirror -Recurse -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Say "跳过镜像（-SkipMirror）：直接用 $Proj 构建"
    $ProjMirror = $Proj
}

$Spec = Join-Path $ProjMirror "packaging\cg5picker.spec"
if (-not (Test-Path $Spec)) { throw "找不到 $Spec" }

# ---------------------------------------------------------------- 4) PyInstaller
$Exe = Join-Path $Dist "CG5Picker\CG5Picker.exe"
if ($SkipBuild -and (Test-Path $Exe)) {
    Say "跳过 PyInstaller（-SkipBuild）：复用已有目录包"
} else {
    Say "PyInstaller 出目录包（onedir，绝不用 onefile —— LGPLv3 要求可替换 Qt 动态库）"
    Push-Location $ProjMirror
    try {
        & $Python -m PyInstaller --noconfirm --clean --distpath $Dist `
            --workpath (Join-Path $BuildRoot "build") $Spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }
    } finally { Pop-Location }
}

if (-not (Test-Path $Exe)) { throw "没找到产物 $Exe" }
$size = [math]::Round(((Get-ChildItem (Split-Path $Exe) -Recurse -File |
        Measure-Object Length -Sum).Sum / 1MB), 1)
Say "目录包：$Exe（约 $size MB）"

# 随包数据必须真的在（LGPLv3 的许可全文 + 使用说明）
foreach ($rel in @("_internal\licenses\NOTICE.txt", "_internal\licenses\LGPL-3.0.txt",
                   "_internal\licenses\GPL-3.0.txt", "_internal\docs\使用说明.html",
                   "_internal\resources\cg5picker.ico")) {
    $p = Join-Path (Split-Path $Exe) $rel
    if (Test-Path $p) { Say "  随包 ✓ $rel" } else { throw "随包少了 $rel" }
}

# ---------------------------------------------------------------- 5) 冒烟测试
#   ★ 断言只用 **ASCII 标记**（CG5Picker / MIT / LGPL / PySide6）：冻结版从管道出来
#     时中文编码跟控制台码页有关，用中文匹配会假失败（踩过）。
#     launcher 里已经把 stdout 切成 UTF-8；这里再把控制台读回也设成 UTF-8，显示才正常。
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
Say "冒烟测试：CG5Picker.exe --version"
$out = & $Exe --version 2>&1 | Out-String
if ($out -notmatch "CG5Picker" -or $out -notmatch "MIT") {
    throw "冻结版 --version 输出异常：$out"
}
Write-Host (($out.Trim() -split "`n" | Select-Object -First 3) -join "`n")
Say "冒烟测试：CG5Picker.exe --licenses"
$lic = & $Exe --licenses 2>&1 | Out-String
if ($lic -notmatch "LGPL" -or $lic -notmatch "PySide6") {
    throw "冻结版 --licenses 输出异常"
}
Say "  --licenses 正常（含 LGPL / PySide6 声明）"
Say "冒烟测试：CG5Picker.exe --smoke（把界面装配一遍，验证包里的 Qt / matplotlib 齐不齐）"
$smoke = & $Exe --smoke 2>&1 | Out-String
if ($smoke -notmatch "smoke OK") { throw "冻结版 --smoke 失败：$smoke" }
Say "  $($smoke.Trim())"
# ★ 默认启动必须**最大化**（用户口径）；--smoke 用的是干净配置，这里正好能验
if ($smoke -notmatch "want_max=True") {
    throw "冻结版默认不是最大化启动（看 smoke 输出里的 want_max）"
}
# ★ 冒烟不能往发行包里写配置（写进去会让用户一打开就不最大化）
if (Test-Path (Join-Path $Dist "CG5Picker\config")) {
    throw "冒烟污染了发行包配置（应写到临时目录）"
}
Say "  冒烟没有污染发行包配置 ✓"

# ---------------------------------------------------------------- 6) Inno Setup
if ($SkipInstaller) { Say "-SkipInstaller：不编安装包"; exit 0 }

$Iss = Join-Path $Here "installer_cg5picker.iss"
# Inno Setup 可能装在任意盘（本机就在 E:\Inno Setup 6）；-Iscc 可显式指定
if (-not $Iscc) {
    $Iscc = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        "E:\Inno Setup 6\ISCC.exe", "D:\Inno Setup 6\ISCC.exe",
        "C:\Inno Setup 6\ISCC.exe", "F:\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Iscc) {
    # 再兜一次：各盘根目录下按名字找（深度 2，够快）
    foreach ($drv in (Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Root)) {
        $hit = Get-ChildItem $drv -Recurse -Depth 2 -Filter "ISCC.exe" -File -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($hit) { $Iscc = $hit.FullName; break }
    }
}

if (-not $Iscc) {
    Warn "没找到 Inno Setup 6 的 ISCC.exe —— 目录包已就绪，安装包没编。"
    Warn "装一个再跑一次即可：winget install -e --id JRSoftware.InnoSetup"
    Warn "（或到 https://jrsoftware.org/isdl.php 下载 Inno Setup 6；"
    Warn "  已经装了但不在常见位置，就用 -Iscc <ISCC.exe 路径> 指定）"
    # 退出码约定：0 = 全部成功；2 = 目录包成功但没编安装包（缺 Inno Setup）；1 = 失败
    exit 2
}
Say "Inno Setup：$Iscc"

# 中文向导：Inno 官方安装包不一定带 ChineseSimplified.isl ——
#   · Inno 自己带了（本机 E:\Inno Setup 6\Languages\ 就有）→ 直接用；
#   · 没带但仓库自带一份（packaging\languages\）→ 注入到 Inno 的 Languages 目录；
#   · 都没有 → 退回英文向导（不影响功能）。
$langDir = Join-Path $Here "languages"
$innoLang = Join-Path (Split-Path $Iscc) "Languages\ChineseSimplified.isl"
$haveChinese = $false
if (Test-Path $innoLang) {
    $haveChinese = $true
    Say "简体中文向导：用 Inno 自带的语言文件"
} elseif (Test-Path (Join-Path $langDir "ChineseSimplified.isl")) {
    Copy-Item (Join-Path $langDir "ChineseSimplified.isl") (Split-Path $innoLang) -Force
    $haveChinese = $true
    Say "简体中文向导：已注入仓库自带的中文语言文件"
} else {
    Warn "没有简体中文向导语言文件，安装向导用英文"
}

$isccArgs = @("/DProjDir=$ProjMirror", "/DBuildRoot=$BuildRoot",
              "/DMyAppVersion=$AppVer")
if ($haveChinese) { $isccArgs += "/DHaveChinese=1" }
$isccArgs += $Iss
Say "编译安装包"
& $Iscc @isccArgs
if ($LASTEXITCODE -ne 0) { throw "ISCC 失败（退出码 $LASTEXITCODE）" }

$Setup = Join-Path $Dist "CG5Picker_Setup_v$AppVer.exe"
if (Test-Path $Setup) {
    $mb = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
    Say "安装包：$Setup（$mb MB）"
} else {
    Warn "ISCC 成功但没找到安装包，检查 OutputDir：$Dist"
    exit 2
}
Say "全部完成（退出码 0）"
exit 0
