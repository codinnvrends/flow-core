@echo off
REM =============================================================================
REM FlowCore — Start Databases + Kafka Only (Windows)
REM 
REM Starts ONLY the persistent stores and message bus:
REM   - PostgreSQL, TimescaleDB, Neo4j, Kafka, Kafka UI
REM
REM Does NOT start any application services.
REM Use this for local development where you run services natively or in IDE.
REM
REM Usage:
REM   .\scripts\start-databases.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "COMPOSE_FILE=%PROJECT_ROOT%\docker\docker-compose.databases.yml"

echo ======================================================
echo   FlowCore — Starting Databases + Kafka
echo ======================================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not running. Please start Docker first.
    exit /b 1
)

REM Start the infrastructure services
echo Starting PostgreSQL, TimescaleDB, Neo4j, and Kafka...
docker compose -f "%COMPOSE_FILE%" up -d
if errorlevel 1 (
    echo Error: Failed to start services.
    exit /b 1
)

REM Wait for services to be healthy
echo.
echo Waiting for services to be healthy...
timeout /t 5 /nobreak >nul

REM Check status
echo.
echo ======================================================
echo   FlowCore Infrastructure Status
echo ======================================================
docker compose -f "%COMPOSE_FILE%" ps

echo.
echo Infrastructure services are starting...
echo.
echo Access URLs:
echo   Neo4j Browser  -^> http://localhost:7474
echo   Kafka UI       -^> http://localhost:8090
echo   PostgreSQL     -^> localhost:5432
echo   TimescaleDB    -^> localhost:5433
echo   Kafka          -^> localhost:9092 (internal) / 19092 (external)
echo.
echo To stop: .\scripts\stop-databases.bat
