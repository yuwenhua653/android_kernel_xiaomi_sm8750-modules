@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0capture_annibale_boot_readiness.py"
) else (
  python "%~dp0capture_annibale_boot_readiness.py"
)
echo.
echo Keep this window open if an error is shown.
pause
