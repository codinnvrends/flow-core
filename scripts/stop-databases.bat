@echo off
REM =============================================================================
REM FlowCore — Stop Databases + Kafka (Windows)
REM 
REM Stops the persistent stores and message bus.
REM Data volumes are preserved for next restart.
REM
REM Usage:
REM   .\scripts\stop-databases.bat
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "COMPOSE_FILE=%PROJECT_ROOT%\docker\docker-compose.databases.yml"

echo ======================================================
echo   FlowCore — Stopping Databases + Kafka
echo ======================================================
echo.

docker compose -f "%COMPOSE_FILE%" down

echo.
echo Infrastructure services stopped.
echo Note: Data volumes are preserved. Use 'docker volume rm' to delete data.
