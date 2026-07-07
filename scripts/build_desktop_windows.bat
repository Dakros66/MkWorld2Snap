@echo off
setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "VENV_DIR=%PROJECT_ROOT%\.venv-win"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

cd /d "%PROJECT_ROOT%" || exit /b 1

if not exist "%VENV_PYTHON%" (
  py -3 -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%\requirements-desktop.txt"
if errorlevel 1 exit /b 1

cd /d "%PROJECT_ROOT%\frontend" || exit /b 1
where pnpm >nul 2>nul
if errorlevel 1 (
  npm install
  if errorlevel 1 exit /b 1
  npm run build
  if errorlevel 1 exit /b 1
) else (
  pnpm install --frozen-lockfile
  if errorlevel 1 pnpm install
  if errorlevel 1 exit /b 1
  pnpm run build
  if errorlevel 1 exit /b 1
)

cd /d "%PROJECT_ROOT%" || exit /b 1
set "PYINSTALLER_CONFIG_DIR=%PROJECT_ROOT%\.pyinstaller-cache"
"%VENV_PYTHON%" -m PyInstaller --clean --noconfirm --distpath "%PROJECT_ROOT%\dist" --workpath "%PROJECT_ROOT%\build" "%PROJECT_ROOT%\MkWorld2Snap.spec"
if errorlevel 1 exit /b 1

echo Built Windows app: %PROJECT_ROOT%\dist\MkWorld2Snap\MkWorld2Snap.exe
