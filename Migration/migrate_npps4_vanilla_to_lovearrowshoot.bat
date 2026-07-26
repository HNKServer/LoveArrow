@echo off
setlocal
cd /d "%~dp0"
if "%~2"=="" (
  echo Usage: %~nx0 "C:\path\to\old-NPPS4" "C:\path\to\NPPS4-v5.32" [gl^|cn]
  echo.
  echo The third argument is the legacy profile. For upstream NPPS4 use gl.
  exit /b 2
)
set "LEGACY=%~3"
if "%LEGACY%"=="" set "LEGACY=gl"
py -3.12 "%~dp0migrate_npps4_vanilla_to_v532.py" --old-root "%~1" --new-root "%~2" --legacy-profile "%LEGACY%"
if errorlevel 1 (
  echo.
  echo Migration failed. Read the error above; backups are not deleted.
  pause
  exit /b 1
)
echo.
echo Migration completed.
pause
