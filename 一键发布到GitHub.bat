@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

rem ================================================================
rem  CG5Picker - one-click publish to GitHub (source + installer)
rem
rem  Repo : https://github.com/pengzhenran/CG5Picker
rem
rem  Usage (double-click, or from cmd):
rem      one-click publish           -> default tag in publish_github.ps1
rem      ... publish v1.0.1          -> publish tag v1.0.1
rem
rem  Needs : git + GitHub CLI (gh) installed, and `gh auth login` done.
rem  Needs : CG5Picker_Setup_<tag>.exe. Build it first with
rem          powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
rem          (or run this file with -Build passed through, see ps1 -Build)
rem
rem  NOTE  : this .bat is intentionally ASCII-only (cmd parses batch files
rem          byte-wise; mixing codepages mangles Chinese prompts). All the
rem          Chinese output comes from publish_github.ps1 -- the `chcp 65001`
rem          above is what keeps it readable in this console.
rem ================================================================

set "PS1=%~dp0packaging\publish_github.ps1"

if not exist "%PS1%" (
  echo [x] not found: "%PS1%"
  echo     this .bat must sit next to the packaging\ folder.
  pause
  exit /b 2
)

where powershell >nul 2>nul
if errorlevel 1 (
  echo [x] powershell not found in PATH
  pause
  exit /b 2
)

if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Tag "%~1"
)
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [ok] publish finished, exit code 0
) else (
  echo [x] publish FAILED, exit code %RC%
)
pause
exit /b %RC%
