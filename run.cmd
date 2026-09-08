@echo off
rem Start the FIT viewer/editor for the .fit files in this folder.
setlocal
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
cd /d "%APP_DIR%"
set "VENV_DIR=%APP_DIR%\.venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv "%VENV_DIR%"
)
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
echo Installing Garmin Connect support...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%APP_DIR%\requirements-garmin.txt"
echo.
echo Virtual environment: %VENV_DIR%
set "APP_URL=http://127.0.0.1:8731/"
echo Starting FIT Editor at %APP_URL%
rem powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%APP_URL%'"
"%VENV_DIR%\Scripts\python.exe" -m fitedit --dir "%APP_DIR%" --no-browser %*
