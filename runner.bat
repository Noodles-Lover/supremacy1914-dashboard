@echo off
set "BASE=%~dp0"
set "MGR_PY=C:\Users\acer\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "VENV=C:\Users\acer\.workbuddy\binaries\python\envs\default"
set "VENV_PY=%VENV%\Scripts\python.exe"

REM 若 venv 被清理（WorkBuddy 更新/重置時常見），自動重建並安裝 websockets，
REM 避免後續 subprocess 因找不到直譯器而噴 [WinError 2]。
if not exist "%VENV_PY%" (
  if exist "%MGR_PY%" (
    "%MGR_PY%" -m venv "%VENV%"
    set "PIP_PROXY="
    set "HTTP_PROXY="
    set "HTTPS_PROXY="
    "%VENV_PY%" -m pip install --quiet --upgrade pip
    "%VENV_PY%" -m pip install --quiet websockets
  )
)

cd /d "%BASE%"
"%VENV_PY%" "%BASE%run_daily.py" >> "%BASE%automation.log" 2>&1
