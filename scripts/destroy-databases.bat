@echo off
REM =============================================================================
REM FlowCore — Destroy Databases (Windows)
REM
REM Stops and removes ONLY the infrastructure containers and their volumes.
REM Application services are unaffected.
REM
REM Usage:
REM   .\scripts\destroy-databases.bat              (interactive)
REM   .\scripts\destroy-databases.bat --force      (skip confirmation)
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "DOCKER_DIR=%PROJECT_ROOT%\docker"
set "COMPOSE_FILE=%DOCKER_DIR%\docker-compose.databases.yml"
set "FORCE=0"

if "%~1"=="--force" set "FORCE=1"

echo.
echo ======================================================
echo   FlowCore -- DESTROY DATABASES
echo ======================================================
echo.
echo WARNING: This will permanently delete:
echo   - flowcore-postgres  (PostgreSQL data)
echo   - flowcore-timescaledb (TimescaleDB data)
echo   - flowcore-neo4j     (Neo4j graph data)
echo   - flowcore-kafka     (Kafka/Redpanda data + topics)
echo   - All associated Docker volumes (ALL DATA WILL BE LOST)
echo.

if %FORCE%==0 (
    set /p "CONFIRM=Are you sure you want to destroy all database data? [y/N] "
    if /i "!CONFIRM!" neq "y" (
        if /i "!CONFIRM!" neq "yes" (
            echo Cancelled.
            exit /b 0
        )
    )
)

echo.
echo Stopping and removing database containers and volumes...
cd /d "%PROJECT_ROOT%"
docker compose -f "%COMPOSE_FILE%" down -v
if errorlevel 1 (
    echo Error: Failed to remove database containers.
    exit /b 1
)

echo.
echo [OK] All database containers and volumes removed.
echo.
echo   PostgreSQL, TimescaleDB, Neo4j, and Kafka data has been wiped.
echo   To re-initialise databases, run:
echo     .\scripts\start-databases.bat       -- restart empty databases
echo     .\scripts\run_all.sh                -- restart + seed with synthetic data
echo.
