@echo off
setlocal enabledelayedexpansion

echo ====================================
echo  Building Luma Viewer for Windows
echo ====================================
echo.

REM Resolve paths relative to this script
set "SCRIPTS_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPTS_DIR%.."
set "OUTPUT_DIR=%SCRIPTS_DIR%output"

cd /d "%PROJECT_DIR%"

REM --- 1. Clean previous artifacts ---
echo [1/4] Cleaning previous artifacts...
if exist "dist"                rmdir /s /q dist
if exist "__pycache__"         rmdir /s /q __pycache__
if exist "%SCRIPTS_DIR%work"   rmdir /s /q "%SCRIPTS_DIR%work"

REM --- 2. Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    pause & exit /b 1
)

REM --- 3. Install / update build dependencies ---
echo [2/4] Installing build dependencies...
pip install --quiet pyinstaller
pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo WARNING: Some dependencies may not have installed correctly.
)

REM --- 4. Build executable with PyInstaller ---
echo [3/4] Building Luma.exe with PyInstaller...
echo.
pyinstaller "%SCRIPTS_DIR%Luma.spec" ^
    --distpath "%OUTPUT_DIR%\dist" ^
    --workpath "%SCRIPTS_DIR%work"

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed.
    pause & exit /b 1
)
echo.
echo Executable ready: %OUTPUT_DIR%\dist\Luma\Luma.exe

REM --- 5. Build installer with Inno Setup (optional) ---
echo [4/4] Building installer...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe"       set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if defined ISCC (
    "%ISCC%" "%SCRIPTS_DIR%setup.iss"
    if errorlevel 1 (
        echo ERROR: Inno Setup compilation failed.
        pause & exit /b 1
    )
    echo Installer: %OUTPUT_DIR%\LumaViewer-0.1.0-Setup-Windows_x64.exe
) else (
    echo Inno Setup 6 not found -- skipping installer creation.
    echo Get it at: https://jrsoftware.org/isinfo.php
    echo Executable folder: %OUTPUT_DIR%\dist\Luma\
)

echo.
echo Build completed successfully!
pause
