@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)"
if errorlevel 1 goto fail
if not exist .venv-qt\Scripts\python.exe py -3 -m venv .venv-qt
if errorlevel 1 goto fail
.venv-qt\Scripts\python.exe -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  .venv-qt\Scripts\python.exe -m pip install -r requirements_qt.txt
  if errorlevel 1 goto fail
)
.venv-qt\Scripts\python.exe qt_editor.py %*
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Check the error above. Python 3.12 or newer and the Python Launcher are required.
pause
exit /b 1
