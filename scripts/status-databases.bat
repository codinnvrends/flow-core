@echo off
REM =============================================================================
REM FlowCore — Check Status of Databases + Kafka (Windows)
REM 
REM Shows running status of infrastructure services.
REM
REM Usage:
REM   .\scripts\status-databases.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "COMPOSE_FILE=%PROJECT_ROOT%\docker\docker-compose.databases.yml"

echo ======================================================
echo   FlowCore Infrastructure Status
echo ======================================================
echo.

REM Check if containers are running
set "RUNNING=0"
for /f %%i in ('docker compose -f "%COMPOSE_FILE%" ps -q 2^>nul ^| find /c /v ""') do set "RUNNING=%%i"

if %RUNNING%==0 (
    echo No infrastructure containers are currently running.
    echo.
    echo To start: .\scripts\start-databases.bat
    exit /b 0
)

REM Show container status
echo Container Status:
docker compose -f "%COMPOSE_FILE%" ps

echo.
echo ======================================================
echo   Access URLs
echo ======================================================
echo   Neo4j Browser  -^> http://localhost:7474
echo   Kafka UI       -^> http://localhost:8090
echo   PostgreSQL     -^> localhost:5432
echo   TimescaleDB    -^> localhost:5433
echo   Kafka          -^> localhost:9092 (internal) / 19092 (external)
