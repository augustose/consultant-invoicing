@echo off
setlocal enabledelayedexpansion
title Consultant Invoicing - Management

:: ── Paths ──────────────────────────────────────────────────────────────────
set "PROJECT_ROOT=%~dp0"
set "LOG_DIR=%PROJECT_ROOT%logs"
set "BACKUP_DIR=%PROJECT_ROOT%backups"
set "STDOUT_LOG=%LOG_DIR%\app_stdout.log"
set "STDERR_LOG=%LOG_DIR%\app_stderr.log"
set "SYSTEM_LOG=%LOG_DIR%\system.log"
set "PID_FILE=%LOG_DIR%\app.pid"

:: ── Ensure directories exist ────────────────────────────────────────────────
if not exist "%LOG_DIR%"    mkdir "%LOG_DIR%"
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

:: ── Colours (requires Windows 10+) ─────────────────────────────────────────
for /f %%a in ('echo prompt $E^| cmd /q') do set "ESC=%%a"
set "CYAN=%ESC%[96m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "RED=%ESC%[91m"
set "BLUE=%ESC%[94m"
set "BOLD=%ESC%[1m"
set "RESET=%ESC%[0m"

call :log INFO "Management script started"

:: ════════════════════════════════════════════════════════════════════════════
:MAIN_LOOP
call :show_banner
call :show_menu
choice /n /c SWKLBDX /m ""
set "KEY=%errorlevel%"

if "%KEY%"=="1" call :start_app false  & goto MAIN_LOOP
if "%KEY%"=="2" call :start_app true   & goto MAIN_LOOP
if "%KEY%"=="3" call :kill_app         & goto MAIN_LOOP
if "%KEY%"=="4" call :view_logs        & goto MAIN_LOOP
if "%KEY%"=="5" call :create_backup    & goto MAIN_LOOP
if "%KEY%"=="6" call :open_docs        & goto MAIN_LOOP
if "%KEY%"=="7" goto :EXIT
goto MAIN_LOOP

:: ════════════════════════════════════════════════════════════════════════════
:show_banner
cls
echo %CYAN%%BOLD%
echo   +==================================================+
echo   ^|                                                  ^|
echo   ^|    CONSULTANT INVOICING - MANAGEMENT             ^|
echo   ^|                                                  ^|
echo   +==================================================+
echo %RESET%
exit /b

:show_menu
echo %BOLD%  Select an action:%RESET%
echo.
echo   %GREEN%[S]%RESET% %BOLD%Start%RESET%     - Launch app (terminal only)
echo   %BLUE%[W]%RESET% %BOLD%Web%RESET%       - Launch app and open browser
echo   %RED%[K]%RESET% %BOLD%Kill%RESET%      - Stop the running app
echo   %YELLOW%[L]%RESET% %BOLD%Logs%RESET%      - View live logs
echo   %YELLOW%[B]%RESET% %BOLD%Backup%RESET%    - Create a backup
echo   %CYAN%[D]%RESET% %BOLD%Docs%RESET%      - Open documentation folder
echo   %RED%[X]%RESET% %BOLD%Exit%RESET%      - Exit this script
echo.
set /p "=  Waiting for key... " <nul
exit /b

:: ════════════════════════════════════════════════════════════════════════════
:start_app
set "OPEN_BROWSER=%~1"
echo.
echo %GREEN%  Starting app with uv...%RESET%
call :kill_app_silent

cd /d "%PROJECT_ROOT%"

if "%OPEN_BROWSER%"=="true" (
    echo %BLUE%  Opening browser at http://localhost:8081 ...%RESET%
    start "" "http://localhost:8081"
)

echo %YELLOW%  Logs: %LOG_DIR%%RESET%
echo %YELLOW%  Press Ctrl+C to stop the app.%RESET%
echo.

call :log INFO "Starting app (browser=%OPEN_BROWSER%)"
uv run python app/main.py >> "%STDOUT_LOG%" 2>> "%STDERR_LOG%"

set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    call :log ERROR "App stopped with error code %EXIT_CODE%"
    echo.
    echo %RED%%BOLD%  ERROR: App stopped unexpectedly (code: %EXIT_CODE%).%RESET%
    echo %YELLOW%  Check logs: %STDERR_LOG%%RESET%
    pause
) else (
    call :log INFO "App stopped normally"
)
exit /b

:kill_app
echo.
call :kill_app_silent
echo %GREEN%  App stopped.%RESET%
call :log INFO "App stopped by user"
timeout /t 2 /nobreak >nul
exit /b

:kill_app_silent
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8081 " ^| findstr "LISTENING"') do (
    echo %YELLOW%  Stopping existing process on port 8081 (PID: %%p)...%RESET%
    taskkill /f /pid %%p >nul 2>&1
)
exit /b

:: ════════════════════════════════════════════════════════════════════════════
:view_logs
echo.
echo %YELLOW%  Showing last 40 lines of logs (press Ctrl+C to stop)...%RESET%
echo.
if exist "%SYSTEM_LOG%"  powershell -command "Get-Content '%SYSTEM_LOG%' -Tail 20"
echo.
if exist "%STDERR_LOG%"  (
    echo %RED%  -- Errors --%RESET%
    powershell -command "Get-Content '%STDERR_LOG%' -Tail 20"
)
echo.
pause
exit /b

:create_backup
echo.
echo %YELLOW%  Creating backup...%RESET%
for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do (
    set "TIMESTAMP=%%a%%b%%c_%%d%%e%%f"
)
set "TIMESTAMP=%TIMESTAMP: =0%"
set "BACKUP_NAME=backup_consultant_%TIMESTAMP%.zip"

powershell -command "Compress-Archive -Path '%PROJECT_ROOT%app', '%PROJECT_ROOT%docs', '%PROJECT_ROOT%pyproject.toml', '%PROJECT_ROOT%uv.lock' -DestinationPath '%BACKUP_DIR%\%BACKUP_NAME%' -Force"

if "%errorlevel%"=="0" (
    call :log INFO "Backup created: %BACKUP_NAME%"
    echo %GREEN%  Backup saved: %BACKUP_DIR%\%BACKUP_NAME%%RESET%
) else (
    echo %RED%  Backup failed.%RESET%
)
timeout /t 2 /nobreak >nul
exit /b

:open_docs
echo.
echo %CYAN%  Opening docs folder...%RESET%
explorer "%PROJECT_ROOT%docs"
call :log INFO "User opened docs folder"
timeout /t 1 /nobreak >nul
exit /b

:: ════════════════════════════════════════════════════════════════════════════
:log
set "LEVEL=%~1"
set "MSG=%~2"
for /f "tokens=1-2 delims=T" %%a in ("%date%T%time%") do (
    echo [%%a %%b] [%LEVEL%] %MSG% >> "%SYSTEM_LOG%"
)
exit /b

:: ════════════════════════════════════════════════════════════════════════════
:EXIT
call :log INFO "Management script closed"
echo.
echo %RED%  Goodbye!%RESET%
echo.
exit /b 0
