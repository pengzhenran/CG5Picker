# -*- coding: utf-8 -*-
<#
  CG5Picker —— 一键发布到 GitHub（源码 + 安装包）

  做什么
    [1/6] 检查 git / gh / 登录状态 / 必备文件
    [2/6] 仓库不存在就建（public），然后把仓库克隆或更新到本地工作目录
    [3/6] 把项目源码镜像到工作目录（robocopy /MIR，排除配置、缓存、构建产物、野外数据）
    [4/6] 检查"不该入库的东西"没混进去
    [5/6] 提交并推送（默认分支钉成 main，否则仓库首页不显示 README）
    [6/6] 建 Release / 更新 Release，上传安装包，打印 SHA256

  用法
    powershell -ExecutionPolicy Bypass -File packaging\publish_github.ps1
    powershell -ExecutionPolicy Bypass -File packaging\publish_github.ps1 -Tag v1.0.1
    powershell -ExecutionPolicy Bypass -File packaging\publish_github.ps1 -Build      # 先重新打包
    powershell -ExecutionPolicy Bypass -File packaging\publish_github.ps1 -SkipRelease
    powershell -ExecutionPolicy Bypass -File packaging\publish_github.ps1 -SetupExe "D:\...\CG5Picker_Setup_v1.0.0.exe"
    powershell -ExecutionPolicy Bypass -File packaging\publish_github.ps1 -Proxy http://127.0.0.1:17897

  网络：github.com 的 git 直连在国内常被重置（`Recv failure: Connection was reset`），
  而 api.github.com 往往是通的。脚本先试**系统代理**（Windows 设置 → 网络和 Internet → 代理 里那个），
  再试直连，谁通用谁，只作用于本次运行；也可以用 -Proxy 显式指定。代理端口变了不用改脚本。

  退出码：0 成功 / 2 前置条件不足（工具、登录、文件、安装包缺失）/ 1 中途失败
#>
[CmdletBinding()]
param(
    # 版本标签（会自动补 v 前缀）
    [string]$Tag = "v1.0.0",
    # 目标仓库 owner/name
    [string]$Repo = "pengzhenran/CG5Picker",
    # 仓库简介（只在新建仓库时用）
    [string]$Description = "CG5Picker — CG-5 重力仪数据挑选：按日期/Survey 圈范围、按条件筛选、图形复核、按原始格式导出 xlsx（Windows 桌面版，不需要 Python）",
    # 项目根目录（默认 = 本脚本所在 packaging\ 的上一级）
    [string]$ProjectDir,
    # 安装包路径（默认在项目根 / D:\CG5Picker_build\dist / 下载目录里找）
    [string]$SetupExe,
    # 本地克隆（工作目录）
    [string]$Work,
    # Release 说明文件
    [string]$NotesFile,
    # HTTP(S) 代理，例：http://127.0.0.1:17897（留空 = 自动：先系统代理，再直连）
    [string]$Proxy,
    # 仓库话题（新建/推送后写一次）
    [string]$Topics = "gravity,geodesy,geophysics,gravimeter,cg5,data-reduction,pyside6,windows",
    # 先跑一遍 packaging\build_installer.ps1 重新出安装包
    [switch]$Build,
    # 只同步源码，不推
    [switch]$SkipPush,
    # 只推源码，不发 Release
    [switch]$SkipRelease
)

# ★ 不用 Stop：原生命令（curl / git / gh）往 stderr 写东西时，Stop 会把它当终止性错误
#   抛出来（踩过：curl 探测超时、git 克隆进度都可能直接把脚本打断）。所有原生命令
#   一律显式查 $LASTEXITCODE，失败就走 Die。
$ErrorActionPreference = "Continue"

function Say  { param([string]$m) Write-Host $m }
function Step { param([string]$n, [string]$m) Write-Host ("[{0}] {1}" -f $n, $m) -ForegroundColor Cyan }
function Good { param([string]$m) Write-Host ("      " + $m) -ForegroundColor Green }
function Warn { param([string]$m) Write-Host ("      " + $m) -ForegroundColor Yellow }
function Die  { param([string]$m, [int]$code = 1) Write-Host ("[x] " + $m) -ForegroundColor Red; exit $code }

# ---------------------------------------------------------------- 前置
if (-not $Tag.StartsWith("v")) { $Tag = "v" + $Tag }
$Asset = "CG5Picker_Setup_{0}.exe" -f $Tag
$Title = "CG5Picker CG-5 数据挑选 {0}" -f $Tag

foreach ($tool in @("git", "gh")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Die ("没找到 {0} —— 装一下：git https://git-scm.com/ ｜ gh https://cli.github.com/" -f $tool) 2
    }
}
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Die "gh 还没登录：先跑 gh auth login" 2 }

# ---------------------------------------------------------------- 网络（git 直连 github.com 常被重置）
function Test-GitHub {
    param([string]$Proxy)
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { return $null }
    $a = @("-s", "-m", "12", "-o", "NUL", "-w", "%{http_code}")
    if ($Proxy) { $a += @("-x", $Proxy) }
    $a += "https://github.com/"
    $code = [string](& curl.exe @a)
    return ($code.Trim() -eq "200")
}

$sysProxy = ""
$inet = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
if ($inet -and $inet.ProxyEnable -eq 1 -and $inet.ProxyServer) {
    $sysProxy = [string]$inet.ProxyServer
    if ($sysProxy -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://") { $sysProxy = "http://" + $sysProxy }
}

# 顺序：显式 -Proxy > 系统代理（探一下通不通）> 直连 > 兜底用系统代理
$useProxy = ""
if ($Proxy) {
    $useProxy = $Proxy
} elseif ($sysProxy -and (Test-GitHub -Proxy $sysProxy) -eq $true) {
    $useProxy = $sysProxy
} elseif ((Test-GitHub) -eq $true) {
    $useProxy = ""
} elseif ($sysProxy) {
    $useProxy = $sysProxy        # curl 不在或探测失败，先按系统代理试
} else {
    Warn "github.com 直连不通、也没探到系统代理 —— 克隆若失败，用 -Proxy http://127.0.0.1:<端口>"
}

if ($useProxy) {
    $env:HTTPS_PROXY = $useProxy; $env:https_proxy = $useProxy
    $env:HTTP_PROXY  = $useProxy; $env:http_proxy  = $useProxy
    # api.github.com 直连本来就是通的，别让它也绕代理
    $env:NO_PROXY = "api.github.com"; $env:no_proxy = "api.github.com"
} else {
    $env:HTTPS_PROXY = ""; $env:https_proxy = ""
    $env:HTTP_PROXY  = ""; $env:http_proxy  = ""
}

# ---------------------------------------------------------------- 项目与安装包
if (-not $ProjectDir) { $ProjectDir = Split-Path -Parent $PSScriptRoot }
if (-not (Test-Path -LiteralPath $ProjectDir)) { Die ("项目目录不存在：{0}" -f $ProjectDir) 2 }
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path

# 必须在项目根里看到这些东西，才敢往下走（尤其后面有 robocopy /MIR）
$required = @("main.py", "README.md", "LICENSE.txt", "requirements.txt", "RELEASE_NOTES.md",
              "pickersrc\window.py", "docs\qr-quark.png", "docs\qr-tvgg.jpg",
              "licenses\NOTICE.txt", "packaging\build_installer.ps1")
$missing = @()
foreach ($rel in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir $rel))) { $missing += $rel }
}
if ($missing.Count -gt 0) { Die ("项目目录里缺文件（{0}）：`n      {1}" -f $ProjectDir, ($missing -join "`n      ")) 2 }

if (-not $NotesFile) { $NotesFile = Join-Path $ProjectDir "RELEASE_NOTES.md" }
if (-not (Test-Path -LiteralPath $NotesFile)) { Die ("缺少 Release 说明：{0}" -f $NotesFile) 2 }

if (-not $Work) { $Work = Join-Path $env:LOCALAPPDATA "CG5Picker-gh" }
$Work = [IO.Path]::GetFullPath($Work)
if ($Work.TrimEnd("\") -eq $ProjectDir.TrimEnd("\")) { Die "工作目录不能就是项目目录（robocopy /MIR 会删掉 .git）" 2 }

Say ""
Say ("==== 发布 {0} → {1} ====" -f $Tag, $Repo)
Say ("      项目   {0}" -f $ProjectDir)
Say ("      工作区 {0}" -f $Work)
if ($useProxy) { Say ("      代理   {0}" -f $useProxy) } else { Say "      代理   不用（直连 github.com 可用）" }
Say ""

if ($Build) {
    Step "0/6" "先重新打包安装包（packaging\build_installer.ps1）"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectDir "packaging\build_installer.ps1")
    if ($LASTEXITCODE -ne 0) { Die ("打包失败（exit {0}）" -f $LASTEXITCODE) 1 }
}

if (-not $SetupExe) {
    $cands = @(
        (Join-Path $ProjectDir $Asset),
        (Join-Path "D:\CG5Picker_build\dist" $Asset),
        (Join-Path $env:USERPROFILE ("Downloads\" + $Asset))
    )
    foreach ($c in $cands) { if (Test-Path -LiteralPath $c) { $SetupExe = $c; break } }
}
if (-not $SetupExe -or -not (Test-Path -LiteralPath $SetupExe)) {
    Die ("没找到安装包 {0}。先跑 packaging\build_installer.ps1，或用 -SetupExe 指路径。" -f $Asset) 2
}
$SetupExe = (Resolve-Path -LiteralPath $SetupExe).Path
$SetupSize = (Get-Item -LiteralPath $SetupExe).Length
$SetupHash = (Get-FileHash -LiteralPath $SetupExe -Algorithm SHA256).Hash
Good ("安装包 {0}（{1:N1} MB）" -f $SetupExe, ($SetupSize / 1MB))
Good ("SHA256 {0}" -f $SetupHash)

# ---------------------------------------------------------------- 1/6 仓库
Step "1/6" ("确认仓库 {0}" -f $Repo)
& gh repo view $Repo *> $null
if ($LASTEXITCODE -ne 0) {
    Warn ("仓库不存在，创建 public 仓库 {0}" -f $Repo)
    & gh repo create $Repo --public --description $Description
    if ($LASTEXITCODE -ne 0) { Die "创建仓库失败" 1 }
} else {
    Good "仓库已存在"
}

# ---------------------------------------------------------------- 2/6 克隆
if (Test-Path -LiteralPath (Join-Path $Work ".git")) {
    Step "2/6" ("更新本地克隆 {0}" -f $Work)
    & git -C $Work pull --ff-only
    if ($LASTEXITCODE -ne 0) { Die ("pull 失败 —— 直接删掉 {0} 重跑也行" -f $Work) 1 }
} else {
    Step "2/6" ("克隆 {0} → {1}" -f $Repo, $Work)
    if (Test-Path -LiteralPath $Work) { Remove-Item -LiteralPath $Work -Recurse -Force }
    $parent = Split-Path -Parent $Work
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
    & gh repo clone $Repo $Work
    if ($LASTEXITCODE -ne 0) {
        Die "克隆失败 —— 若报 Connection was reset / timed out，就是 git 直连 github.com 被重置：加 -Proxy http://127.0.0.1:<端口>" 1
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $Work ".git"))) { Die ("{0} 不是 git 仓库，停下（不拿它做 /MIR 目标）" -f $Work) 1 }

# git 不认 WinINET 的系统代理：把本次用的代理写进这个克隆的配置（换端口重跑会自动改写）
if ($useProxy) {
    & git -C $Work config http.proxy $useProxy
    & git -C $Work config https.proxy $useProxy
} else {
    & git -C $Work config --unset http.proxy 2>$null
    & git -C $Work config --unset https.proxy 2>$null
}

foreach ($kv in @(@("user.name", "zhenran"), @("user.email", "45099481+pengzhenran@users.noreply.github.com"))) {
    $cur = & git -C $Work config $kv[0]
    if (-not $cur) { & git -C $Work config $kv[0] $kv[1] | Out-Null }
}

# 空仓库时本地可能是 master，而 GitHub 新仓库默认 main —— 统一 main，后面还会钉一次默认分支
$branch = & git -C $Work symbolic-ref --short HEAD
if ($branch -ne "main") {
    Warn ("本地分支 {0} → main" -f $branch)
    & git -C $Work checkout -B main 2>&1 | Out-Null
}

# ---------------------------------------------------------------- 3/6 镜像源码
Step "3/6" "同步源码（robocopy /MIR）"
# ★ /XD 只写**目录名**（不写全路径）：写全路径时只排除源里那个路径，目标里的 .git
#   不在排除范围内，/MIR 会把刚克隆下来的 .git 删掉（实测踩过：之后 git 全线报
#   "not a git repository"）。按名字排除才对两边都生效。
$rcArgs = @($ProjectDir, $Work, "/MIR", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
$rcArgs += @("/XD", ".git", ".venv", "venv", "__pycache__", "config", "build", "dist", ".idea", ".vscode")
$rcArgs += @("/XF", "1465_20250702.txt", "version_info.txt", "*.xlsx")
& robocopy @rcArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { Die ("robocopy 失败（exit {0}）" -f $rc) 1 }
Good ("robocopy 完成（exit {0}：0=无变化 1=有更新 2=有删除 3=两者都有）" -f $rc)
if (-not (Test-Path -LiteralPath (Join-Path $Work ".git"))) { Die "同步后 .git 没了（/MIR 的排除项没生效），停下" 1 }

# ---------------------------------------------------------------- 4/6 卫生检查
Step "4/6" "检查不该入库的东西"
$status = @(& git -C $Work status --porcelain)
if ($LASTEXITCODE -ne 0) { Die "git status 失败，工作目录不是仓库？" 1 }
$forbidden = @("config/settings.json", "config/presets.json", "__pycache__", ".pyc", ".xlsx",
               "1465_20250702.txt", "version_info.txt")
$hits = @()
foreach ($line in $status) {
    foreach ($p in $forbidden) { if ($line -like ("*" + $p + "*")) { $hits += $line; break } }
}
if ($hits.Count -gt 0) {
    Die ("这些文件不该进仓库（检查 .gitignore / robocopy 排除项）：`n      " + ($hits -join "`n      ")) 1
}
Good ("待提交改动 {0} 条" -f $status.Count)

# ---------------------------------------------------------------- 5/6 提交推送
if ($SkipPush) {
    Step "5/6" "跳过提交与推送（-SkipPush）"
} else {
    Step "5/6" "提交并推送"
    & git -C $Work add -A
    $dirty = @(& git -C $Work status --porcelain)
    if ($dirty.Count -eq 0) {
        Good "没有变化，跳过提交"
    } else {
        & git -C $Work commit -m ("发布 {0}：源码 + README（网盘/公众号二维码）+ 发行说明" -f $Tag) | Out-Null
        if ($LASTEXITCODE -ne 0) { Die "commit 失败" 1 }
        & git -C $Work push -u origin main
        if ($LASTEXITCODE -ne 0) { Die "push 失败" 1 }
        Good "已推送"
    }
    # 默认分支不是 main 的话仓库首页不显示 README；话题顺手写一次
    & gh repo edit $Repo --default-branch main --add-topic $Topics *> $null
    $n = @(& git -C $Work ls-files).Count
    Good ("仓库里现在有 {0} 个文件" -f $n)
}

# ---------------------------------------------------------------- 6/6 Release
if ($SkipRelease) {
    Step "6/6" "跳过 Release（-SkipRelease）"
} else {
    Step "6/6" ("发布 Release {0}" -f $Tag)
    $tmp = Join-Path $env:TEMP $Asset
    Copy-Item -LiteralPath $SetupExe -Destination $tmp -Force
    & gh release view $Tag -R $Repo *> $null
    if ($LASTEXITCODE -eq 0) {
        Warn ("Release {0} 已存在，覆盖资产并更新说明" -f $Tag)
        & gh release upload $Tag $tmp -R $Repo --clobber
        if ($LASTEXITCODE -ne 0) { Die "上传资产失败" 1 }
        & gh release edit $Tag -R $Repo --title $Title --notes-file $NotesFile --latest
        if ($LASTEXITCODE -ne 0) { Die "更新 Release 失败" 1 }
    } else {
        & gh release create $Tag $tmp -R $Repo --title $Title --notes-file $NotesFile --latest
        if ($LASTEXITCODE -ne 0) { Die "创建 Release 失败" 1 }
    }
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    Good ("资产 {0}" -f $Asset)
}

Say ""
Say "==== 完成 ===="
Say ("  资产    {0}（{1:N1} MB / {2} 字节）" -f $Asset, ($SetupSize / 1MB), $SetupSize)
Say ("  SHA256  {0}" -f $SetupHash)
Say ("  仓库    https://github.com/{0}" -f $Repo)
Say ("  发行页  https://github.com/{0}/releases/tag/{1}" -f $Repo, $Tag)
Say ""
exit 0
