@echo off
REM =============================================================================
REM FlowCore — Check Status of Application Services (Windows)
REM
REM Shows the status of all locally-running FlowCore services started by
REM start-services.bat. Reads the PID file; falls back to port scan if missing.
REM
REM Usage:
REM   .\scripts\status-services.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "PID_FILE=%TEMP%\flowcore-services.pids"

echo ======================================================
echo   FlowCore Application Services Status
echo ======================================================
echo.

if not exist "%PID_FILE%" (
    echo No PID file found: %PID_FILE%
    echo Falling back to port scan...
    echo.

    set "RUNNING=0"
    set "STOPPED=0"

    for %%S in (
        "dcim-ingestion:8001"
        "telemetry-gateway:8002"
        "active-discovery:8003"
        "graph-updater:8010"
        "timeseries-writer:8011"
        "event-archive:8012"
        "graph-api:4000"
        "insights-api:4001"
        "eventing-integration:4002"
        "topology-agent:8020"
        "classification-agent:8021"
    ) do (
        for /f "tokens=1,2 delims=:" %%A in ("%%~S") do (
            set "SVC=%%A"
            set "PORT=%%B"
            netstat -aon 2>nul | findstr /R "[:.]!PORT! .*LISTENING" >nul 2>&1
            if !errorlevel!==0 (
                echo   [UP]    !SVC! — :!PORT!
                set /a RUNNING+=1
            ) else (
                echo   [DOWN]  !SVC! — :!PORT!
                set /a STOPPED+=1
            )
        )
    )

    echo.
    echo ======================================================
    echo   Running: !RUNNING!   Stopped: !STOPPED!
    echo ======================================================
    if !RUNNING! GTR 0 (
        echo.
        echo Access URLs:
        echo   Graph API ^(GraphQL^) -^> http://localhost:4000/graphql
        echo   Insights API        -^> http://localhost:4001
        echo   Eventing            -^> http://localhost:4002
    ) else (
        echo.
        echo No services running. Start with: .\scripts\start-services.bat
    )
    goto :eof
)

echo Service Processes ^(from PID file^):
echo.

set "RUNNING=0"
set "STOPPED=0"

for /f "tokens=1,2,3 delims=:" %%A in (%PID_FILE%) do (
    set "SVC=%%A"
    set "PID=%%B"
    set "PORT=%%C"
    if "!PID!"=="" goto :next_line

    REM Check if the PID is still alive
    tasklist /FI "PID eq !PID!" 2>nul | findstr "!PID!" >nul 2>&1
    if !errorlevel!==0 (
        echo   [UP]    !SVC! — PID !PID!, :!PORT!
        set /a RUNNING+=1
    ) else (
        echo   [DOWN]  !SVC! — PID !PID! ^(exited^), :!PORT!
        set /a STOPPED+=1
    )
    :next_line
)

echo.
echo ======================================================
echo   Running: %RUNNING%   Stopped: %STOPPED%
echo ======================================================

if %RUNNING% GTR 0 (
    echo.
    echo Access URLs:
    echo   Graph API ^(GraphQL^) -^> http://localhost:4000/graphql
    echo   Insights API        -^> http://localhost:4001
    echo   Eventing            -^> http://localhost:4002
    echo.
    echo Logs:  %%TEMP%%\flowcore-logs\^<service-name^>.log
    echo Stop:  .\scripts\stop-services.bat
) else (
    echo.
    echo No services running. Start with: .\scripts\start-services.bat
)
