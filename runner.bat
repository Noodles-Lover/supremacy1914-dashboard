@echo off
set "BASE=%~dp0"
cd /d "%BASE%"
"C:\Users\acer\.workbuddy\binaries\python\envs\default\Scripts\python.exe" "%BASE%run_daily.py" >> "%BASE%automation.log" 2>&1
