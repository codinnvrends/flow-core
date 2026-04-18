@echo off
REM =============================================================================
REM FlowCore — Verify Full Stack (Windows)
REM
REM Checks health of ALL containers and HTTP endpoints.
REM Exits with 0 if everything is healthy, 1 if any check fails.
REM
REM Usage:
REM   .\scripts\verify-all.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "ENV_FILE=%PROJECT_ROOT%\docker\.env"

set "PASS=0"
set "FAIL=0"
set "FAIL_LIST="

REM Load ports from .env with defaults
set "API_PORT=8888"
set "KC_PORT=8080"
set "KAFKA_UI_PORT=8090"
set "MLFLOW_PORT=5000"
set "REPLAY_PORT=8050"

for /f "tokens=1,* delims==" %%a in ('type "%ENV_FILE%" ^| findstr /v "^#" ^| findstr /v "^$"') do (
    if "%%a"=="API_GATEWAY_PORT"  set "API_PORT=%%b"
    if "%%a"=="KEYCLOAK_PORT"     set "KC_PORT=%%b"
    if "%%a"=="REDPANDA_UI_PORT"  set "KAFKA_UI_PORT=%%b"
    if "%%a"=="MLFLOW_PORT"       set "MLFLOW_PORT=%%b"
    if "%%a"=="REPLAY_PORT"       set "REPLAY_PORT=%%b"
)

echo.
echo ======================================================
echo   FlowCore Full Stack Verification
echo ======================================================
echo.

REM ── Infrastructure containers ──────────────────────────────────────────────
echo --- Infrastructure Containers ---
call :check_container flowcore-postgres "PostgreSQL"
call :check_container flowcore-timescaledb "TimescaleDB"
call :check_container flowcore-neo4j "Neo4j"
call :check_container flowcore-kafka "Kafka (Redpanda)"
call :check_container flowcore-kafka-ui "Kafka UI"

REM ── Application containers ────────────────────────────────────────────────
echo.
echo --- Application Containers ---
call :check_container flowcore-platform "Platform"
call :check_container flowcore-agents "Agents"
call :check_container flowcore-api-ui "API + UI"
call :check_container flowcore-replay "Synthetic Replay"

REM ── HTTP endpoints ────────────────────────────────────────────────────────
echo.
echo --- HTTP Endpoint Checks ---
call :check_http "http://localhost:%API_PORT%/health" "NOC Gateway /health"
call :check_http "http://localhost:%API_PORT%/api/insights/" "Insights API"
call :check_http "http://localhost:%KC_PORT%" "Keycloak"
call :check_http "http://localhost:%KAFKA_UI_PORT%" "Kafka UI"
call :check_http "http://localhost:%MLFLOW_PORT%" "MLflow UI"
call :check_http "http://localhost:%REPLAY_PORT%/health" "Replay /health"

REM ── Summary ───────────────────────────────────────────────────────────────
echo.
echo ======================================================
echo   Verification Summary
echo ======================================================
echo   PASS: %PASS%   FAIL: %FAIL%
echo.
if %FAIL% gtr 0 (
    echo Failed checks:
    echo %FAIL_LIST%
    echo.
    exit /b 1
) else (
    echo All checks passed -- FlowCore stack is healthy!
    echo.
    exit /b 0
)

REM ── Subroutines ───────────────────────────────────────────────────────────
:check_container
set "CTR=%~1"
set "LBL=%~2"
docker inspect --format="{{.State.Status}}" %CTR% >nul 2>&1
if errorlevel 1 (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] %LBL% -- container not found"
    echo   [FAIL] %LBL% -- container not found
    goto :eof
)
for /f %%s in ('docker inspect --format "{{.State.Status}}" %CTR% 2^>nul') do set "STATUS=%%s"
if "!STATUS!"=="running" (
    set /a PASS+=1
    echo   [PASS] %LBL% -- running
) else (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] %LBL% -- status: !STATUS!"
    echo   [FAIL] %LBL% -- status: !STATUS!
)
goto :eof

:check_http
set "URL=%~1"
set "LBL=%~2"
curl -sf --max-time 5 "%URL%" >nul 2>&1
if errorlevel 1 (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] %LBL% -- HTTP failed (%URL%)"
    echo   [FAIL] %LBL% -- HTTP request failed (%URL%)
) else (
    set /a PASS+=1
    echo   [PASS] %LBL% -- HTTP OK
)
goto :eof
