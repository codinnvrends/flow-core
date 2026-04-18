@echo off
REM =============================================================================
REM FlowCore — Verify Databases + Kafka (Windows)
REM
REM Checks health of ONLY the infrastructure tier.
REM Exits 0 if all pass, 1 if any fail.
REM
REM Usage:
REM   .\scripts\verify-databases.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "PASS=0"
set "FAIL=0"
set "FAIL_LIST="

echo.
echo ======================================================
echo   FlowCore Infrastructure Verification
echo ======================================================
echo.

REM ── Container status ──────────────────────────────────────────────────────
echo --- Container Status ---
call :check_container flowcore-postgres "PostgreSQL"
call :check_container flowcore-timescaledb "TimescaleDB"
call :check_container flowcore-neo4j "Neo4j"
call :check_container flowcore-kafka "Kafka (Redpanda)"
call :check_container flowcore-kafka-ui "Kafka UI"

REM ── Connectivity tests ────────────────────────────────────────────────────
echo.
echo --- Connectivity Tests ---

REM PostgreSQL query
docker exec flowcore-postgres psql -U flowcore -d flowcore --no-align --tuples-only -c "SELECT 1;" >nul 2>&1
if errorlevel 1 (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] PostgreSQL -- SELECT 1 failed"
    echo   [FAIL] PostgreSQL -- SELECT 1 failed
) else (
    set /a PASS+=1
    echo   [PASS] PostgreSQL -- SELECT 1 OK
)

REM TimescaleDB query
docker exec flowcore-timescaledb psql -U flowcore -d flowcore_ts --no-align --tuples-only -c "SELECT 1;" >nul 2>&1
if errorlevel 1 (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] TimescaleDB -- SELECT 1 failed"
    echo   [FAIL] TimescaleDB -- SELECT 1 failed
) else (
    set /a PASS+=1
    echo   [PASS] TimescaleDB -- SELECT 1 OK
)

REM Neo4j bolt
docker exec flowcore-neo4j cypher-shell -u neo4j -p flowcore_secret "RETURN 1;" >nul 2>&1
if errorlevel 1 (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] Neo4j -- Bolt query failed"
    echo   [FAIL] Neo4j -- Bolt query failed
) else (
    set /a PASS+=1
    echo   [PASS] Neo4j -- Bolt query OK
)

REM Kafka health
docker exec flowcore-kafka rpk cluster health >nul 2>&1
if errorlevel 1 (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] Kafka -- cluster health check failed"
    echo   [FAIL] Kafka -- cluster health check failed
) else (
    set /a PASS+=1
    echo   [PASS] Kafka -- cluster healthy
)

REM ── Port checks (host-side via curl/nc) ───────────────────────────────────
echo.
echo --- Host Port Availability ---

for %%P in (5432 5433 7474 7687 9092 8090) do (
    curl -sf --max-time 3 "http://localhost:%%P" >nul 2>&1
    REM For non-HTTP ports curl will fail, use a TCP test
    powershell -Command "try { $t = New-Object Net.Sockets.TcpClient; $t.Connect('localhost', %%P); $t.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        set /a FAIL+=1
        echo   [FAIL] Port %%P -- not reachable
        set "FAIL_LIST=!FAIL_LIST! [FAIL] Port %%P not reachable"
    ) else (
        set /a PASS+=1
        echo   [PASS] Port %%P -- open
    )
)

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
    echo All infrastructure checks passed -- databases and Kafka are healthy!
    echo.
    exit /b 0
)

REM ── Subroutines ───────────────────────────────────────────────────────────
:check_container
set "CTR=%~1"
set "LBL=%~2"
for /f %%s in ('docker inspect --format "{{.State.Status}}" %CTR% 2^>nul') do set "STATUS=%%s"
if "!STATUS!"=="" (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] %LBL% -- not found"
    echo   [FAIL] %LBL% -- container not found
) else if "!STATUS!"=="running" (
    set /a PASS+=1
    echo   [PASS] %LBL% -- running
) else (
    set /a FAIL+=1
    set "FAIL_LIST=!FAIL_LIST! [FAIL] %LBL% -- status: !STATUS!"
    echo   [FAIL] %LBL% -- status: !STATUS!
)
goto :eof
