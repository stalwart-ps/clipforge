@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
"%~dp0.venv\Scripts\python.exe" "%~dp0backend\run.py" --desktop
pause