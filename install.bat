@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  CARL Installation
echo ============================================================
echo.

REM ---- Check Python ------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Please install Python 3.11 from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if !PY_MAJOR! LSS 3 (
    echo ERROR: Python 3.10 or later is required. Found Python !PY_VER!.
    pause
    exit /b 1
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo ERROR: Python 3.10 or later is required. Found Python !PY_VER!.
    pause
    exit /b 1
)
echo Found Python !PY_VER!

REM ---- Create virtual environment ----------------------------
echo.
echo Creating virtual environment...
if exist venv (
    echo Virtual environment already exists. Skipping creation.
) else (
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM ---- Install requirements ----------------------------------
echo.
echo Installing requirements (this may take several minutes on first run)...
echo Note: torch is a large download ~200 MB. Please be patient.
echo.
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed. Check the output above for details.
    pause
    exit /b 1
)

REM ---- Create launcher ---------------------------------------
echo.
echo Creating launcher (run_carl.bat)...
(
    echo @echo off
    echo call "%%~dp0venv\Scripts\activate.bat"
    echo python "%%~dp0CARL\run_ui.py"
    echo deactivate
) > run_carl.bat

echo.
echo ============================================================
echo  Installation complete!
echo.
echo  To start CARL: double-click run_carl.bat
echo  Or from this folder: run_carl.bat
echo ============================================================
echo.
pause
