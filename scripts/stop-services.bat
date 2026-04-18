@echo off
REM =============================================================================
REM FlowCore — Stop Application Services (Windows)
REM
REM Stops all locally-running FlowCore services started by start-services.bat.
REM Databases and Kafka (Docker) are left running.
REM
REM Usage:
REM   .\scripts\stop-services.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "PID_FILE=%TEMP%\flowcore-services.pids"
set "LOG_DIR=%TEMP%\flowcore-logs"

echo ======================================================
echo   FlowCore -- Stopping Application Services
echo ======================================================
echo.

set "STOPPED=0"

if exist "%PID_FILE%" (
    REM Read PID file: format is name:pid:port
    for /f "tokens=1,2,3 delims=:" %%a in (%PID_FILE%) do (
        set "SVC=%%a"
        set "PID=%%b"
        set "PORT=%%c"
        tasklist /FI "PID eq %%b" 2>nul | findstr /I "%%b" >nul
        if not errorlevel 1 (
            taskkill /PID %%b /F >nul 2>&1
            echo   [STOPPED] %%a (PID %%b, :%%c)
            set /a STOPPED+=1
        ) else (
            echo   [GONE]    %%a (PID %%b already exited)
        )
    )
    del /f "%PID_FILE%" >nul 2>&1
) else (
    echo No PID file found. Attempting to stop by port...
    for %%P in (8001 8002 8003 8010 8011 8012 4000 4001 4002 8020 8021 8050) do (
        for /f "tokens=5" %%i in ('netstat -aon ^| findstr ":%%P " ^| findstr "LISTENING"') do (
            taskkill /PID %%i /F >nul 2>&1
            echo   [STOPPED] :%%P (PID %%i)
            set /a STOPPED+=1
        )
    )
)

echo.
echo Stopped %STOPPED% service(s).
echo Note: Databases and Kafka (Docker) are still running.
echo.
echo Logs preserved at: %LOG_DIR%\
echo To stop databases: .\scripts\stop-databases.bat
