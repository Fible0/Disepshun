@echo off
title Disepshun Builder
setlocal
cd /d "%~dp0"
set "BUILD_DIR=%~dp0.pyinstaller-build"
rem Only remove a temporary folder created by this run.
if exist "%BUILD_DIR%" (
    echo Temporary build folder already exists: "%BUILD_DIR%"
    echo Remove it after checking its contents, then try again.
    pause
    exit /b 1
)
mkdir "%BUILD_DIR%"
if errorlevel 1 exit /b 1
rem One-folder mode: the game starts without unpacking itself to a temporary folder on every launch.
pyinstaller -D -n Disepshun --windowed --noconfirm --optimize 2 --icon "%~dp0assets\icon.ico" --add-data "%~dp0assets;assets" --collect-all panda3d --distpath "%~dp0dist" --workpath "%BUILD_DIR%\work" --specpath "%BUILD_DIR%" "%~dp0Main.py"
set "BUILD_RESULT=%ERRORLEVEL%"
rem BUILD_DIR is the fixed folder under this script's directory, created above.
rmdir /s /q "%BUILD_DIR%"
if not "%BUILD_RESULT%"=="0" (
    echo Build failed.
    pause
    exit /b %BUILD_RESULT%
)
if exist "%BUILD_DIR%" (
    echo Build succeeded, but temporary files could not be removed.
    pause
    exit /b 1
)
echo Built "%~dp0dist\Disepshun\Disepshun.exe" (share the whole dist\Disepshun folder)
pause
exit /b 0
