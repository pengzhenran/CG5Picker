@echo off
setlocal
title CG5 Data Picker

rem ---------------------------------------------------------------------
rem  ASCII-only on purpose.  A cmd batch file is re-parsed line by line, so
rem  switching the code page inside the file makes cmd mis-decode whatever
rem  non-ASCII bytes follow it.  Keep this file 7-bit clean.
rem ---------------------------------------------------------------------

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

set "PY="
if exist "%HERE%\.venv\Scripts\python.exe" set "PY=%HERE%\.venv\Scripts\python.exe"
if not defined PY if exist "%HERE%\..\GravProc\.venv\Scripts\python.exe" set "PY=%HERE%\..\GravProc\.venv\Scripts\python.exe"

if not defined PY (
  echo.
  echo [ERROR] No usable Python environment found.
  echo.
  echo Looked for:
  echo   1^) %HERE%\.venv\Scripts\python.exe
  echo   2^) %HERE%\..\GravProc\.venv\Scripts\python.exe
  echo.
  echo Create a venv in this folder and install the dependencies:
  echo   python -m venv .venv
  echo   .venv\Scripts\python -m pip install PySide6 numpy matplotlib openpyxl
  echo.
  pause
  exit /b 1
)

"%PY%" "%HERE%\main.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [ERROR] The program exited with code %RC%.
  echo If a traceback is shown above, please send a screenshot.
  pause
)
exit /b %RC%
