@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)"
if errorlevel 1 goto python_error
if not exist .venv-qt\Scripts\python.exe py -3 -m venv .venv-qt
if errorlevel 1 goto fail
.venv-qt\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto fail
.venv-qt\Scripts\python.exe -m pip install -r requirements_qt.txt "pyinstaller>=6,<7"
if errorlevel 1 goto fail
.venv-qt\Scripts\python.exe -m unittest discover -s tests -q
if errorlevel 1 goto fail
set QT_QPA_PLATFORM=offscreen
.venv-qt\Scripts\python.exe tests\qt_preview_smoke.py
if errorlevel 1 goto qt_test_fail
.venv-qt\Scripts\python.exe tests\qt_grid_smoke.py
if errorlevel 1 goto qt_test_fail
.venv-qt\Scripts\python.exe tests\qt_editor_smoke.py
if errorlevel 1 goto qt_test_fail
.venv-qt\Scripts\python.exe tests\qt_segments_smoke.py
if errorlevel 1 goto qt_test_fail
.venv-qt\Scripts\python.exe tests\qt_junction_markers_smoke.py
if errorlevel 1 goto qt_test_fail
.venv-qt\Scripts\python.exe tests\qt_consumed_tips_smoke.py
if errorlevel 1 goto qt_test_fail
set QT_QPA_PLATFORM=
.venv-qt\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --exclude-module tkinter --name VerilogCanvasQt qt_editor.py
if errorlevel 1 goto fail
echo.
echo Ready: dist\VerilogCanvasQt.exe
echo Full Qt editor. Open existing .vsch files or create a new schematic.
pause
exit /b 0
:python_error
echo Python 3.12 or newer and the Python Launcher are required.
pause
exit /b 1
:qt_test_fail
set QT_QPA_PLATFORM=
:fail
echo Build failed. Review the error above.
pause
exit /b 1
