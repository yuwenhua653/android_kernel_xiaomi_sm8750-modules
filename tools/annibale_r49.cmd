@echo off
setlocal
cd /d "%~dp0"
echo Redmi K90 annibale / OS4.0.6.0.XPKCNXM / R49 TEST CANDIDATE
echo 1. Verify package files (no device access)
echo 2. Temporary kernel boot (NO FLASH; stock network modules)
echo 3. INSTALL kernel and network modules (WRITES THREE PARTITIONS)
echo 4. RESTORE original three images (keep state-r49.json)
echo 5. Collect boot and module evidence
echo 6. Reboot original system after TEMPORARY BOOT ONLY
echo 7. Exit
choice /c 1234567 /n /m "Select: "
if errorlevel 7 exit /b 0
if errorlevel 6 (set "SCRIPT=trial_annibale_hyperos.py"& set "TASK=return-stock"& goto run)
if errorlevel 5 (set "SCRIPT=trial_annibale_hyperos.py"& set "TASK=collect"& goto run)
if errorlevel 4 (set "SCRIPT=install_annibale_hyperos.py"& set "TASK=restore"& goto run)
if errorlevel 3 (set "SCRIPT=install_annibale_hyperos.py"& set "TASK=install"& goto run)
if errorlevel 2 (set "SCRIPT=trial_annibale_hyperos.py"& set "TASK=trial"& goto run)
set "SCRIPT=install_annibale_hyperos.py"
set "TASK=verify"
:run
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0%SCRIPT%" %TASK%
) else (
  python "%~dp0%SCRIPT%" %TASK%
)
pause
