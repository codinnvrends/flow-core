@echo off
REM =============================================================================
REM FlowCore — Synthetic Replay Controller (Windows)
REM
REM Controls the synthetic-replay service that publishes to Kafka topics:
REM   metrics.timeseries.raw  (60%)
REM   dcim.config.normalized  (20%)
REM   discovery.snmp.results   (5%)
REM   discovery.bmc.results    (5%)
REM   alerts.raw              (~0.5%)
REM
REM Usage:
REM   .\scripts\replay.bat start [--mode live|historical] [--rate N]
REM   .\scripts\replay.bat stop
REM   .\scripts\replay.bat status
REM   .\scripts\replay.bat pause
REM   .\scripts\replay.bat resume
REM   .\scripts\replay.bat rate <events_per_sec>
REM   .\scripts\replay.bat reset
REM   .\scripts\replay.bat logs
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "DOCKER_DIR=%PROJECT_ROOT%\docker"
set "ENV_FILE=%DOCKER_DIR%\.env"
set "REPLAY_COMPOSE=%DOCKER_DIR%\docker-compose.replay.yml"
set "DB_COMPOSE=%DOCKER_DIR%\docker-compose.databases.yml"
set "REPLAY_PORT=8050"
set "REPLAY_API=http://localhost:%REPLAY_PORT%"

REM Load REPLAY_PORT from .env if set
for /f "tokens=1,* delims==" %%a in ('type "%ENV_FILE%" 2^>nul ^| findstr /v "^#" ^| findstr "REPLAY_PORT"') do (
    if "%%a"=="REPLAY_PORT" set "REPLAY_PORT=%%b" & set "REPLAY_API=http://localhost:%%b"
)

set "COMMAND=%~1"
if "%COMMAND%"=="" set "COMMAND=help"
shift

if /i "%COMMAND%"=="start"   goto cmd_start
if /i "%COMMAND%"=="stop"    goto cmd_stop
if /i "%COMMAND%"=="status"  goto cmd_status
if /i "%COMMAND%"=="pause"   goto cmd_pause
if /i "%COMMAND%"=="resume"  goto cmd_resume
if /i "%COMMAND%"=="rate"    goto cmd_rate
if /i "%COMMAND%"=="reset"   goto cmd_reset
if /i "%COMMAND%"=="logs"    goto cmd_logs
if /i "%COMMAND%"=="help"    goto cmd_help
if /i "%COMMAND%"=="--help"  goto cmd_help

echo [replay] Unknown command: %COMMAND%
echo Run: .\scripts\replay.bat help
exit /b 1

REM =============================================================================
:cmd_start
REM =============================================================================
set "REPLAY_MODE=live"
set "REPLAY_RATE="

:parse_start_args
if "%~1"=="" goto do_start
if /i "%~1"=="--mode"       set "REPLAY_MODE=%~2" & shift & shift & goto parse_start_args
if /i "%~1"=="--mode=live"  set "REPLAY_MODE=live" & shift & goto parse_start_args
if /i "%~1"=="--mode=historical" set "REPLAY_MODE=historical" & shift & goto parse_start_args
if /i "%~1"=="--rate"       set "REPLAY_RATE=%~2" & shift & shift & goto parse_start_args
shift & goto parse_start_args

:do_start
REM Check if already running
curl -sf --max-time 3 "%REPLAY_API%/health" >nul 2>&1
if not errorlevel 1 (
    echo [replay] ! Service already running at %REPLAY_API%
    goto cmd_status
)

REM Check Kafka
docker ps --format "{{.Names}}" 2>nul | findstr /C:"flowcore-kafka" >nul
if errorlevel 1 (
    echo [replay] ERROR: Kafka not running. Start it first: .\scripts\start-databases.bat
    exit /b 1
)

echo.
echo ======================================================
echo   Starting Synthetic Replay (Docker)
echo ======================================================
echo   Mode: %REPLAY_MODE%
if defined REPLAY_RATE echo   Rate: %REPLAY_RATE% events/s
echo.

set "REPLAY_MODE=%REPLAY_MODE%"
if defined REPLAY_RATE set "REPLAY_EVENTS_PER_SEC=%REPLAY_RATE%"

cd /d "%PROJECT_ROOT%"
docker compose -f "%DB_COMPOSE%" -f "%REPLAY_COMPOSE%" --env-file "%ENV_FILE%" up -d synthetic-replay
if errorlevel 1 (
    echo [replay] ERROR: Failed to start container
    exit /b 1
)

REM Wait for API
echo [replay] Waiting for replay API on :%REPLAY_PORT%...
set /a WAIT=0
:wait_loop
curl -sf --max-time 2 "%REPLAY_API%/health" >nul 2>&1
if not errorlevel 1 goto api_ready
set /a WAIT+=1
if %WAIT% geq 30 (
    echo [replay] ERROR: API did not come up after 30s
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_loop

:api_ready
echo [replay] API is up
goto cmd_status

REM =============================================================================
:cmd_stop
REM =============================================================================
echo.
echo ======================================================
echo   Stopping Synthetic Replay
echo ======================================================
echo.
cd /d "%PROJECT_ROOT%"
docker compose -f "%DB_COMPOSE%" -f "%REPLAY_COMPOSE%" --env-file "%ENV_FILE%" stop synthetic-replay 2>nul
docker compose -f "%DB_COMPOSE%" -f "%REPLAY_COMPOSE%" --env-file "%ENV_FILE%" rm -f synthetic-replay 2>nul
echo [replay] Stopped
exit /b 0

REM =============================================================================
:cmd_status
REM =============================================================================
echo.
echo ======================================================
echo   Replay Service Status
echo ======================================================
echo.

for /f %%s in ('docker ps --format "{{.Names}}" 2^>nul ^| findstr "flowcore-replay"') do (
    set "CTR_RUNNING=1"
)

if not defined CTR_RUNNING (
    echo   [!] Not running
    echo.
    exit /b 0
)

docker ps --filter "name=flowcore-replay" --format "  Container: {{.Names}}  Status: {{.Status}}"

echo.
echo   API status (%REPLAY_API%/status):
curl -sf --max-time 5 "%REPLAY_API%/status" 2>nul
echo.
echo.
echo   Controls:
echo     .\scripts\replay.bat pause         -- pause publishing
echo     .\scripts\replay.bat resume        -- resume publishing
echo     .\scripts\replay.bat rate ^<N^>      -- change events/sec
echo     .\scripts\replay.bat reset         -- reload seed data + restart
echo.
exit /b 0

REM =============================================================================
:cmd_pause
REM =============================================================================
curl -sf --max-time 5 "%REPLAY_API%/health" >nul 2>&1
if errorlevel 1 (
    echo [replay] ERROR: API not reachable at %REPLAY_API%
    exit /b 1
)
curl -sf -X POST "%REPLAY_API%/control/pause"
echo.
echo [replay] Paused
exit /b 0

REM =============================================================================
:cmd_resume
REM =============================================================================
curl -sf --max-time 5 "%REPLAY_API%/health" >nul 2>&1
if errorlevel 1 (
    echo [replay] ERROR: API not reachable at %REPLAY_API%
    exit /b 1
)
curl -sf -X POST "%REPLAY_API%/control/resume"
echo.
echo [replay] Resumed
exit /b 0

REM =============================================================================
:cmd_rate
REM =============================================================================
set "RATE=%~1"
if "%RATE%"=="" (
    echo [replay] ERROR: Usage: .\scripts\replay.bat rate ^<events_per_sec^>
    exit /b 1
)
curl -sf --max-time 5 "%REPLAY_API%/health" >nul 2>&1
if errorlevel 1 (
    echo [replay] ERROR: API not reachable at %REPLAY_API%
    exit /b 1
)
curl -sf -X POST "%REPLAY_API%/control/rate" ^
    -H "Content-Type: application/json" ^
    -d "{\"events_per_sec\": %RATE%}"
echo.
echo [replay] Rate set to %RATE% events/sec
exit /b 0

REM =============================================================================
:cmd_reset
REM =============================================================================
curl -sf --max-time 5 "%REPLAY_API%/health" >nul 2>&1
if errorlevel 1 (
    echo [replay] ERROR: API not reachable at %REPLAY_API%
    exit /b 1
)
echo [replay] Reloading seed data and restarting...
curl -sf -X POST "%REPLAY_API%/control/reset"
echo.
echo [replay] Reset complete
exit /b 0

REM =============================================================================
:cmd_logs
REM =============================================================================
docker logs flowcore-replay 2>nul
if errorlevel 1 (
    echo [replay] ERROR: Container flowcore-replay not found
    exit /b 1
)
exit /b 0

REM =============================================================================
:cmd_help
REM =============================================================================
echo.
echo FlowCore Synthetic Replay Controller
echo.
echo Usage:
echo   .\scripts\replay.bat ^<command^> [options]
echo.
echo Commands:
echo   start   [--mode live^|historical] [--rate N]
echo             Start replay container (live mode by default)
echo   stop      Stop the replay service
echo   status    Show container status + live API state
echo   pause     Pause message publishing (keeps service running)
echo   resume    Resume message publishing
echo   rate ^<N^>  Change publishing rate to N events/sec
echo   reset     Reload seed data from DB and restart replay
echo   logs      Show container logs
echo.
echo Examples:
echo   .\scripts\replay.bat start                      -- live mode, default rate
echo   .\scripts\replay.bat start --rate 500           -- 500 events/sec
echo   .\scripts\replay.bat start --mode historical    -- replay 30-day seed data
echo   .\scripts\replay.bat rate 2000                  -- update rate live
echo.
echo Topics published:
echo   metrics.timeseries.raw  (60%%)   dcim.config.normalized (20%%)
echo   discovery.snmp.results   (5%%)   discovery.bmc.results   (5%%)
echo   alerts.raw             (~0.5%%)
echo.
exit /b 0
