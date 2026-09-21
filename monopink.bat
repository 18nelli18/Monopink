@echo off
rem MonopInk launcher (Windows).  Double-click to start the web interface,
rem or run "monopink.bat --help" in a terminal for the command line.
setlocal
cd /d "%~dp0"
set "VENV=%~dp0.venv"

if "%~1"=="setup" goto setup
if not exist "%VENV%\Scripts\python.exe" goto setup
"%VENV%\Scripts\python.exe" -c "import serial, PIL" >nul 2>&1 || goto setup
goto run

:setup
where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")
echo == Creating the Python environment in .venv\
%PY% -m venv "%VENV%" || (
  echo MonopInk needs Python 3.8+ : https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause
  exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || (pause & exit /b 1)
echo == Ready.
if "%~1"=="setup" (
  "%VENV%\Scripts\python.exe" -m monopink doctor
  exit /b
)

:run
"%VENV%\Scripts\python.exe" -m monopink %*
if errorlevel 1 pause
