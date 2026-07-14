@echo off
setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

if "%MKWORLD2SNAP_BUILD_CAPTURED%"=="" (
  set "MKWORLD2SNAP_BUILD_CAPTURED=1"
  if not exist "%PROJECT_ROOT%\build_logs" mkdir "%PROJECT_ROOT%\build_logs"
  set "BUILD_STAMP="
  where powershell >nul 2>nul
  if not errorlevel 1 (
    for /f "delims=" %%A in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%A"
  )
  if "!BUILD_STAMP!"=="" set "BUILD_STAMP=%RANDOM%-%RANDOM%"
  set "MKWORLD2SNAP_BUILD_LOG_FILE=%PROJECT_ROOT%\build_logs\windows-build-!BUILD_STAMP!.log"
  set "MKWORLD2SNAP_BUILD_SCRIPT=%~f0"

  where powershell >nul 2>nul
  if errorlevel 1 (
    call "%~f0" > "!MKWORLD2SNAP_BUILD_LOG_FILE!" 2>&1
    set "BUILD_EXIT=!errorlevel!"
    type "!MKWORLD2SNAP_BUILD_LOG_FILE!"
  ) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$log=$env:MKWORLD2SNAP_BUILD_LOG_FILE; $script=$env:MKWORLD2SNAP_BUILD_SCRIPT; & $script 2>&1 | Tee-Object -FilePath $log; exit $LASTEXITCODE"
    set "BUILD_EXIT=!errorlevel!"
  )

  echo.
  echo Log saved to:
  echo !MKWORLD2SNAP_BUILD_LOG_FILE!
  echo.
  if not "%CI%"=="true" pause
  exit /b !BUILD_EXIT!
)

echo ========================================
echo MkWorld2Snap Windows build
echo Project: %PROJECT_ROOT%
echo ========================================
echo.
if /I "%PROJECT_ROOT:~0,7%"=="C:\Mac\" (
  echo [WARN] The project is inside a Parallels shared Mac folder.
  echo The build will be mirrored to a native Windows folder to avoid npm/Vite link issues.
  echo.
  if not "%MKWORLD2SNAP_NATIVE_MIRROR%"=="1" (
    if "%MKWORLD2SNAP_NATIVE_ROOT%"=="" (
      set "MKWORLD2SNAP_NATIVE_ROOT=%LOCALAPPDATA%\MkWorld2Snap\windows-build-source"
    )
    echo Native build folder:
    echo !MKWORLD2SNAP_NATIVE_ROOT!
    echo.
    if not exist "!MKWORLD2SNAP_NATIVE_ROOT!" mkdir "!MKWORLD2SNAP_NATIVE_ROOT!"
    robocopy "%PROJECT_ROOT%" "!MKWORLD2SNAP_NATIVE_ROOT!" /MIR /NFL /NDL /NJH /NJS /XD "%PROJECT_ROOT%\.git" "%PROJECT_ROOT%\.venv" "%PROJECT_ROOT%\.venv-win" "%PROJECT_ROOT%\.venv-universal2" "%PROJECT_ROOT%\.pytest_cache" "%PROJECT_ROOT%\.pyinstaller-cache" "%PROJECT_ROOT%\.tools" "%PROJECT_ROOT%\build" "%PROJECT_ROOT%\build_logs" "%PROJECT_ROOT%\dist" "%PROJECT_ROOT%\frontend\node_modules" "%PROJECT_ROOT%\frontend\dist"
    set "ROBOCOPY_EXIT=!errorlevel!"
    if !ROBOCOPY_EXIT! GEQ 8 (
      echo [ERROR] Could not mirror the project to a native Windows folder.
      goto :error
    )
    set "MKWORLD2SNAP_NATIVE_MIRROR=1"
    set "MKWORLD2SNAP_SHARED_ROOT=%PROJECT_ROOT%"
    call "!MKWORLD2SNAP_NATIVE_ROOT!\scripts\build_desktop_windows.bat"
    set "NATIVE_BUILD_EXIT=!errorlevel!"
    if !NATIVE_BUILD_EXIT! EQU 0 (
      echo.
      echo Copying built dist back to the shared project folder...
      robocopy "!MKWORLD2SNAP_NATIVE_ROOT!\dist" "%PROJECT_ROOT%\dist" /MIR /NFL /NDL /NJH /NJS
      set "ROBOCOPY_EXIT=!errorlevel!"
      if !ROBOCOPY_EXIT! GEQ 8 (
        echo [ERROR] Build succeeded, but copying dist back to the shared folder failed.
        echo Native dist remains available at:
        echo !MKWORLD2SNAP_NATIVE_ROOT!\dist
        exit /b 1
      )
      echo Dist copied to:
      echo %PROJECT_ROOT%\dist
      echo Cleaning native build folder...
      rmdir /s /q "!MKWORLD2SNAP_NATIVE_ROOT!" 2>nul
    )
    exit /b !NATIVE_BUILD_EXIT!
  )
)

set "VENV_DIR=%PROJECT_ROOT%\.venv-win"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BASE_PYTHON_ARCH="
set "BASE_PYTHON_DIR="
set "EMBEDDED_PYTHON=0"
set "ARCH_PROBE_FILE=%PROJECT_ROOT%\build_logs\python_arch_probe.py"
set "NPM_CMD="
set "NODE_VERSION=22.23.1"
set "NODE_PACKAGE=node-v%NODE_VERSION%-win-x64"
set "NODE_TOOLS_DIR=%PROJECT_ROOT%\.tools"
set "NODE_DIR=%NODE_TOOLS_DIR%\%NODE_PACKAGE%"
set "NODE_ZIP=%PROJECT_ROOT%\build_logs\%NODE_PACKAGE%.zip"
set "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/%NODE_PACKAGE%.zip"
set "PYTHON_PTH_FILE="
set "SELECTED_PYTHON="
set "VENV_PYTHON_ARCH="

cd /d "%PROJECT_ROOT%" || goto :error
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Content -Encoding ASCII -Path $env:ARCH_PROBE_FILE -Value @('import platform, sysconfig', 'target = sysconfig.get_platform().lower()', 'print(\"ARM64\" if \"arm64\" in target else \"AMD64\" if \"amd64\" in target else platform.machine())')"
if errorlevel 1 goto :error

echo [1/7] Checking Python...
if not "%PYTHON_BIN%"=="" (
  if not exist "%PYTHON_BIN%" (
    echo [ERROR] PYTHON_BIN points to a file that does not exist:
    echo %PYTHON_BIN%
    goto :error
  )
  set "SELECTED_PYTHON=%PYTHON_BIN%"
  for %%I in ("%PYTHON_BIN%") do set "BASE_PYTHON_DIR=%%~dpI"
  for /f "delims=" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$python=$env:PYTHON_BIN; $probe=$env:ARCH_PROBE_FILE; & $python $probe"') do set "BASE_PYTHON_ARCH=%%A"
  echo Using PYTHON_BIN:
  echo %PYTHON_BIN%
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python launcher "py" was not found.
    echo Install Python 3 for Windows and enable "Add python.exe to PATH".
    goto :error
  )
  for /f "delims=" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$probe=$env:ARCH_PROBE_FILE; & py -3 $probe"') do set "BASE_PYTHON_ARCH=%%A"
  set "SELECTED_PYTHON=py -3"
  echo Using Python launcher: py -3
)

echo Python architecture: %BASE_PYTHON_ARCH%
if "%BASE_PYTHON_ARCH%"=="" (
  echo [ERROR] Could not detect the selected Python architecture.
  goto :error
)
if /I "%BASE_PYTHON_ARCH%"=="ARM64" (
  if /I not "%MKWORLD2SNAP_ALLOW_ARM64%"=="1" (
    echo [ERROR] This Python is ARM64, so PyInstaller would create an ARM64 app.
    echo For normal Windows PCs, install Windows x64 Python 3.12 or 3.13 and run:
    echo set PYTHON_BIN=C:\Path\To\Python312\python.exe
    echo scripts\build_desktop_windows.bat
    echo.
    echo To intentionally build ARM64, set MKWORLD2SNAP_ALLOW_ARM64=1.
    goto :error
  )
)

if not "%PYTHON_BIN%"=="" (
  for %%F in ("%BASE_PYTHON_DIR%python*._pth") do (
    if exist "%%~fF" (
      set "EMBEDDED_PYTHON=1"
      set "PYTHON_PTH_FILE=%%~fF"
    )
  )
)

if "%EMBEDDED_PYTHON%"=="1" (
  echo Embedded Python detected:
  echo %PYTHON_BIN%
  echo Runtime path file:
  echo %PYTHON_PTH_FILE%
  set "VENV_PYTHON=%PYTHON_BIN%"
) else if exist "%VENV_PYTHON%" (
  for /f "delims=" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$python=$env:VENV_PYTHON; $probe=$env:ARCH_PROBE_FILE; & $python $probe"') do set "VENV_PYTHON_ARCH=%%A"
  if not "%VENV_PYTHON_ARCH%"=="%BASE_PYTHON_ARCH%" (
    echo [ERROR] Existing .venv-win uses %VENV_PYTHON_ARCH%, but selected Python is %BASE_PYTHON_ARCH%.
    echo Delete this folder and run the build again:
    echo %VENV_DIR%
    goto :error
  )
)

if "%EMBEDDED_PYTHON%"=="1" (
  echo [2/7] Preparing embedded Python...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=$env:PYTHON_PTH_FILE; $lines=Get-Content $p; $lines=$lines -replace '^#import site$', 'import site'; if ($lines -notcontains 'import site') { $lines += 'import site' }; Set-Content -Encoding ASCII -Path $p -Value $lines"
  if errorlevel 1 goto :error

  "%VENV_PYTHON%" -m pip --version >nul 2>nul
  if errorlevel 1 (
    echo Installing pip into embedded Python...
    set "GET_PIP_FILE=%PROJECT_ROOT%\build_logs\get-pip.py"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile $env:GET_PIP_FILE"
    if errorlevel 1 goto :error
    "%VENV_PYTHON%" "!GET_PIP_FILE!"
    if errorlevel 1 goto :error
  )
) else if not exist "%VENV_PYTHON%" (
  echo [2/7] Creating virtual environment...
  if not "%PYTHON_BIN%"=="" (
    "%PYTHON_BIN%" -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
  ) else (
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
  )
) else (
  echo [2/7] Reusing virtual environment...
)

echo [3/7] Installing Python dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error
if "%EMBEDDED_PYTHON%"=="1" (
  "%VENV_PYTHON%" -m pip install --no-build-isolation -r "%PROJECT_ROOT%\requirements-desktop.txt"
  if errorlevel 1 goto :error
) else (
  "%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%\requirements-desktop.txt"
  if errorlevel 1 goto :error
)
"%VENV_PYTHON%" -m pip show fastapi pyinstaller pywebview >nul
if errorlevel 1 (
  echo [ERROR] Python dependencies are incomplete after installation.
  goto :error
)

echo [4/7] Checking Node.js/npm...
where npm >nul 2>nul
if errorlevel 1 (
  echo npm was not found in PATH. Preparing portable Node.js %NODE_VERSION% x64...
  if not exist "%NODE_DIR%\node.exe" (
    if not exist "%NODE_TOOLS_DIR%" mkdir "%NODE_TOOLS_DIR%"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$url=$env:NODE_URL; $zip=$env:NODE_ZIP; $target=$env:NODE_TOOLS_DIR; Write-Host ('Downloading ' + $url); Invoke-WebRequest -Uri $url -OutFile $zip; Expand-Archive -Path $zip -DestinationPath $target -Force"
    if errorlevel 1 goto :error
  )
  if not exist "%NODE_DIR%\npm.cmd" (
    echo [ERROR] Portable npm was not found after extracting Node.js.
    goto :error
  )
  set "PATH=%NODE_DIR%;%PATH%"
  set "NPM_CMD=%NODE_DIR%\npm.cmd"
) else (
  set "NPM_CMD=npm"
)
call "%NPM_CMD%" --version
if errorlevel 1 goto :error

echo [5/7] Building frontend...
cd /d "%PROJECT_ROOT%\frontend" || goto :error
where pnpm >nul 2>nul
if errorlevel 1 (
  echo pnpm not found. Using npm.
  call "%NPM_CMD%" install
  if errorlevel 1 goto :error
  call "%NPM_CMD%" run build
  if errorlevel 1 goto :error
) else (
  echo pnpm found. Using pnpm.
  call pnpm install --frozen-lockfile
  if errorlevel 1 call pnpm install
  if errorlevel 1 goto :error
  call pnpm run build
  if errorlevel 1 goto :error
)

echo [6/7] Verifying bundled resources...
cd /d "%PROJECT_ROOT%" || goto :error
if not exist "%PROJECT_ROOT%\frontend\dist" (
  echo [ERROR] frontend\dist was not created.
  goto :error
)
if not exist "%PROJECT_ROOT%\profiles" (
  echo [ERROR] profiles directory was not found.
  goto :error
)
if not exist "%PROJECT_ROOT%\rules" (
  echo [ERROR] rules directory was not found.
  goto :error
)

echo [7/7] Creating Windows executable with PyInstaller...
set "PYINSTALLER_CONFIG_DIR=%PROJECT_ROOT%\.pyinstaller-cache"
"%VENV_PYTHON%" -m PyInstaller --clean --noconfirm --distpath "%PROJECT_ROOT%\dist" --workpath "%PROJECT_ROOT%\build" "%PROJECT_ROOT%\MkWorld2Snap.spec"
if errorlevel 1 goto :error

if not exist "%PROJECT_ROOT%\dist\MkWorld2Snap.exe" (
  echo [ERROR] PyInstaller finished but the exe was not found.
  goto :error
)

echo.
echo ========================================
echo [OK] Windows app built successfully.
echo Exe:
echo %PROJECT_ROOT%\dist\MkWorld2Snap.exe
echo ========================================
exit /b 0

:error
echo.
echo ========================================
echo [FAILED] Windows build stopped.
echo Read the lines above or open the saved log file.
echo ========================================
exit /b 1
