@echo off
REM =============================================================================
REM FlowCore — Start Application Services Locally (Windows)
REM
REM Starts all 11 FlowCore services natively using uvicorn (no Docker).
REM Databases and Kafka must already be running in Docker.
REM
REM Prerequisites:
REM   .\scripts\start-databases.bat        (start Postgres, TimescaleDB, Neo4j, Kafka)
REM
REM Usage:
REM   .\scripts\start-services.bat              (Start all services)
REM   .\scripts\start-services.bat --replay     (Also start synthetic-replay)
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "SERVICES_DIR=%PROJECT_ROOT%\services"
set "ENV_FILE=%PROJECT_ROOT%\docker\.env"
set "PID_FILE=%TEMP%\flowcore-services.pids"
set "LOG_DIR=%TEMP%\flowcore-logs"

echo ======================================================
echo   FlowCore -- Starting Application Services (Local)
echo ======================================================
echo.

REM Check Docker is running (needed for databases)
docker info >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not running. Databases need Docker.
    exit /b 1
)

REM Check databases are running
echo Checking databases are running...
docker ps --format "{{.Names}}" | findstr /C:"flowcore-postgres" >nul
if errorlevel 1 (
    echo Error: PostgreSQL not running. Run .\scripts\start-databases.bat first.
    exit /b 1
)
docker ps --format "{{.Names}}" | findstr /C:"flowcore-kafka" >nul
if errorlevel 1 (
    echo Error: Kafka not running. Run .\scripts\start-databases.bat first.
    exit /b 1
)
echo Databases are running.
echo.

REM Find Python (prefer project venv)
set "PYTHON="
if exist "%PROJECT_ROOT%\venv\Scripts\python.exe" (
    set "PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe"
) else if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    echo Error: Python not found. Set up a venv at %PROJECT_ROOT%\venv\
    exit /b 1
)
echo Using Python: %PYTHON%

REM Load env vars from docker/.env
set "PG_HOST=localhost"
set "PG_PORT=5432"
set "TS_HOST=localhost"
set "TS_PORT=5433"
set "NEO4J_HOST=localhost"
set "NEO4J_BOLT_PORT=7687"
set "KAFKA_BOOTSTRAP_SERVERS=localhost:19092"

REM Load port overrides from .env
for /f "tokens=1,* delims==" %%a in ('type "%ENV_FILE%" 2^>nul ^| findstr /v "^#" ^| findstr /v "^$"') do (
    if "%%a"=="PG_PASSWORD"               set "PG_PASSWORD=%%b"
    if "%%a"=="TS_PASSWORD"               set "TS_PASSWORD=%%b"
    if "%%a"=="NEO4J_PASSWORD"            set "NEO4J_PASSWORD=%%b"
    if "%%a"=="PG_USER"                   set "PG_USER=%%b"
    if "%%a"=="TS_USER"                   set "TS_USER=%%b"
    if "%%a"=="PG_DB"                     set "PG_DB=%%b"
    if "%%a"=="TS_DB"                     set "TS_DB=%%b"
    if "%%a"=="DCIM_INGESTION_PORT"       set "DCIM_INGESTION_PORT=%%b"
    if "%%a"=="TELEMETRY_GATEWAY_HTTP_PORT" set "TELEMETRY_GATEWAY_HTTP_PORT=%%b"
    if "%%a"=="ACTIVE_DISCOVERY_PORT"     set "ACTIVE_DISCOVERY_PORT=%%b"
    if "%%a"=="GRAPH_UPDATER_PORT"        set "GRAPH_UPDATER_PORT=%%b"
    if "%%a"=="TIMESERIES_WRITER_PORT"    set "TIMESERIES_WRITER_PORT=%%b"
    if "%%a"=="EVENT_ARCHIVE_PORT"        set "EVENT_ARCHIVE_PORT=%%b"
    if "%%a"=="GRAPH_API_INTERNAL_PORT"   set "GRAPH_API_INTERNAL_PORT=%%b"
    if "%%a"=="INSIGHTS_API_INTERNAL_PORT" set "INSIGHTS_API_INTERNAL_PORT=%%b"
    if "%%a"=="EVENTING_API_INTERNAL_PORT" set "EVENTING_API_INTERNAL_PORT=%%b"
    if "%%a"=="TOPO_AGENT_PORT"           set "TOPO_AGENT_PORT=%%b"
    if "%%a"=="CLASS_AGENT_PORT"          set "CLASS_AGENT_PORT=%%b"
    if "%%a"=="REPLAY_PORT"               set "REPLAY_PORT=%%b"
)

REM Apply default ports if not set
if not defined DCIM_INGESTION_PORT        set "DCIM_INGESTION_PORT=8001"
if not defined TELEMETRY_GATEWAY_HTTP_PORT set "TELEMETRY_GATEWAY_HTTP_PORT=8002"
if not defined ACTIVE_DISCOVERY_PORT      set "ACTIVE_DISCOVERY_PORT=8003"
if not defined GRAPH_UPDATER_PORT         set "GRAPH_UPDATER_PORT=8010"
if not defined TIMESERIES_WRITER_PORT     set "TIMESERIES_WRITER_PORT=8011"
if not defined EVENT_ARCHIVE_PORT         set "EVENT_ARCHIVE_PORT=8012"
if not defined GRAPH_API_INTERNAL_PORT    set "GRAPH_API_INTERNAL_PORT=4000"
if not defined INSIGHTS_API_INTERNAL_PORT set "INSIGHTS_API_INTERNAL_PORT=4001"
if not defined EVENTING_API_INTERNAL_PORT set "EVENTING_API_INTERNAL_PORT=4002"
if not defined TOPO_AGENT_PORT            set "TOPO_AGENT_PORT=8020"
if not defined CLASS_AGENT_PORT           set "CLASS_AGENT_PORT=8021"
if not defined REPLAY_PORT                set "REPLAY_PORT=8050"

REM Parse flags
set "INCLUDE_REPLAY="
if "%~1"=="--replay"      set "INCLUDE_REPLAY=1"
if "%~1"=="--with-replay" set "INCLUDE_REPLAY=1"

REM Setup dirs and reset PID file
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if exist "%PID_FILE%" del /f "%PID_FILE%"

echo Starting platform services...
call :start_service "dcim-ingestion"      %DCIM_INGESTION_PORT%        "DCIM Ingestion"
call :start_service "telemetry-gateway"   %TELEMETRY_GATEWAY_HTTP_PORT% "Telemetry Gateway"
call :start_service "active-discovery"    %ACTIVE_DISCOVERY_PORT%      "Active Discovery"
call :start_service "graph-updater"       %GRAPH_UPDATER_PORT%         "Graph Updater"
call :start_service "timeseries-writer"   %TIMESERIES_WRITER_PORT%     "Timeseries Writer"
call :start_service "event-archive"       %EVENT_ARCHIVE_PORT%         "Event Archive"

echo.
echo Starting API services...
call :start_service "graph-api"            %GRAPH_API_INTERNAL_PORT%    "Graph API (GraphQL)"
call :start_service "insights-api"         %INSIGHTS_API_INTERNAL_PORT% "Insights API"
call :start_service "eventing-integration" %EVENTING_API_INTERNAL_PORT% "Eventing Integration"

echo.
echo Starting agent services...
call :start_service "topology-agent"       %TOPO_AGENT_PORT%            "Topology Agent"
call :start_service "classification-agent" %CLASS_AGENT_PORT%           "Classification Agent"

if defined INCLUDE_REPLAY (
    echo.
    echo Starting synthetic replay...
    call :start_service "synthetic-replay" %REPLAY_PORT% "Synthetic Replay"
)

echo.
echo ======================================================
echo   All services started locally
echo ======================================================
echo.
echo Access URLs:
echo   DCIM Ingestion       -^> http://localhost:%DCIM_INGESTION_PORT%
echo   Telemetry Gateway    -^> http://localhost:%TELEMETRY_GATEWAY_HTTP_PORT%
echo   Active Discovery     -^> http://localhost:%ACTIVE_DISCOVERY_PORT%
echo   Graph Updater        -^> http://localhost:%GRAPH_UPDATER_PORT%
echo   Timeseries Writer    -^> http://localhost:%TIMESERIES_WRITER_PORT%
echo   Event Archive        -^> http://localhost:%EVENT_ARCHIVE_PORT%
echo   Graph API (GraphQL)  -^> http://localhost:%GRAPH_API_INTERNAL_PORT%/graphql
echo   Insights API         -^> http://localhost:%INSIGHTS_API_INTERNAL_PORT%
echo   Eventing             -^> http://localhost:%EVENTING_API_INTERNAL_PORT%
echo   Topology Agent       -^> http://localhost:%TOPO_AGENT_PORT%
echo   Classification Agent -^> http://localhost:%CLASS_AGENT_PORT%
if defined INCLUDE_REPLAY (
echo   Synthetic Replay     -^> http://localhost:%REPLAY_PORT%
)
echo.
echo Logs: %LOG_DIR%\^<service-name^>.log
echo Stop: .\scripts\stop-services.bat
echo PIDs: %PID_FILE%
exit /b 0

REM =============================================================================
:start_service
REM  %1 = service folder name, %2 = port, %3 = display label
REM =============================================================================
set "SVC_NAME=%~1"
set "SVC_PORT=%~2"
set "SVC_LABEL=%~3"
set "SVC_DIR=%SERVICES_DIR%\%SVC_NAME%"
set "LOG_FILE=%LOG_DIR%\%SVC_NAME%.log"

if not exist "%SVC_DIR%\main.py" (
    echo   [SKIP] %SVC_LABEL% -- %SVC_DIR%\main.py not found
    goto :eof
)

start /B "" "%PYTHON%" -m uvicorn main:app ^
    --host 0.0.0.0 ^
    --port %SVC_PORT% ^
    --log-level info ^
    --app-dir "%SVC_DIR%" ^
    >> "%LOG_FILE%" 2>&1

echo   [OK] %SVC_LABEL% -- :%SVC_PORT% -- log: %LOG_FILE%
goto :eof
