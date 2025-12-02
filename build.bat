@echo off
rem PyInstaller build helper for EdgeLiveViewer
rem Usage: build_pyinstaller.bat [onefile|onedir] [console|noconsole]

setlocal

set "ENTRY=main.py"
set "NAME=EdgeLiveViewer"

echo.
echo Building %ENTRY% into %NAME% using PyInstaller
echo.

python -c "import PyInstaller" 2>nul
if %ERRORLEVEL% neq 0 (
  echo PyInstaller is not installed.
  echo Install with: python -m pip install pyinstaller
  pause
  exit /b 1
)

rem Clean previous build artifacts
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%NAME%.spec" del /q "%NAME%.spec"

rem Default options: onefile + console. Use %1 to override: onefile|onedir, %2 console|noconsole
set "MODE=onefile"
set "CONSOLE=console"
if /i "%~1"=="onedir" set "MODE=onedir"
if /i "%~2"=="noconsole" set "CONSOLE=noconsole"

set "OPTS=--noconfirm --clean"
if /i "%MODE%"=="onefile" set "OPTS=%OPTS% --onefile"
if /i "%MODE%"=="onedir" set "OPTS=%OPTS% --onedir"
if /i "%CONSOLE%"=="noconsole" set "OPTS=%OPTS% --noconsole"

echo Running: python -m PyInstaller %OPTS% --name "%NAME%" "%ENTRY%"
python -m PyInstaller %OPTS% --name "%NAME%" "%ENTRY%"
if %ERRORLEVEL% neq 0 (
  echo.
  echo Build failed with error %ERRORLEVEL%.
  pause
  exit /b %ERRORLEVEL%
)

echo.
echo Build succeeded. Output:
if exist "dist\%NAME%.exe" (
  echo   dist\%NAME%.exe
) else (
  echo   dist\%NAME%\
)
echo.
pause

endlocal
