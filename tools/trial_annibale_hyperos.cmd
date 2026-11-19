@echo off
setlocal
cd /d "%~dp0"
echo Redmi K90 annibale / HyperOS OS4.0.6 ONLY
echo 1. Check baseline and temporarily boot R45 once (NO FLASH)
echo 2. Reboot normally to existing stock system (NO FLASH)
echo 3. Collect boot evidence
echo 4. Exit
choice /c 1234 /n /m "Select: "
if errorlevel 4 exit /b 0
if errorlevel 3 (set "TASK=collect") else if errorlevel 2 (set "TASK=return-stock") else (set "TASK=trial")
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0trial_annibale_hyperos.py" %TASK%
) else (
  python "%~dp0trial_annibale_hyperos.py" %TASK%
)
pause
