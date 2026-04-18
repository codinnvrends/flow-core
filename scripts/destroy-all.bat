@echo off
REM =============================================================================
REM FlowCore — Destroy All (Windows)
REM
REM Stops ALL containers, removes ALL volumes, and deletes the shared network.
REM This is a DESTRUCTIVE operation — all data will be lost.
REM
REM Usage:
REM   .\scripts\destroy-all.bat              (interactive confirmation)
REM   .\scripts\destroy-all.bat --force      (skip confirmation)
REM   .\scripts\destroy-all.bat --purge-images  (also remove built images)
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "DOCKER_DIR=%PROJECT_ROOT%\docker"
set "COMPOSE_FILE=%DOCKER_DIR%\docker-compose.full.yml"
set "DB_COMPOSE=%DOCKER_DIR%\docker-compose.databases.yml"
set "ENV_FILE=%DOCKER_DIR%\.env"

set "FORCE=0"
set "PURGE_IMAGES=0"

REM Parse arguments
:parse_args
if "%~1"=="--force" (
    set "FORCE=1"
    shift
    goto parse_args
)
if "%~1"=="--purge-images" (
    set "PURGE_IMAGES=1"
    shift
    goto parse_args
)

echo.
echo ======================================================
echo   FlowCore -- DESTROY ALL
echo ======================================================
echo.
echo WARNING: This will permanently delete:
echo   - All FlowCore Docker containers
echo   - All FlowCore Docker volumes (ALL DATA WILL BE LOST)
echo   - The flowcore_flowcore-net Docker network
if %PURGE_IMAGES%==1 (
    echo   - All locally-built FlowCore images
)
echo.

REM Confirmation prompt
if %FORCE%==0 (
    set /p "CONFIRM=Are you sure you want to destroy everything? [y/N] "
    if /i "!CONFIRM!" neq "y" (
        if /i "!CONFIRM!" neq "yes" (
            echo Cancelled.
            exit /b 0
        )
    )
)

REM Step 1: Bring down full stack with volume wipe
echo.
echo [Step 1/3] Stopping all containers and wiping all volumes...
cd /d "%PROJECT_ROOT%"
docker compose -f "%COMPOSE_FILE%" --env-file "%ENV_FILE%" down -v 2>nul
if errorlevel 1 (
    echo   Full stack down failed -- trying database compose directly...
    docker compose -f "%DB_COMPOSE%" down -v 2>nul
)
echo   [OK] Stack torn down

REM Step 2: Force-remove any stray flowcore containers
echo.
echo [Step 2/3] Removing any stray FlowCore containers...
for /f "tokens=*" %%i in ('docker ps -aq --filter "name=flowcore" 2^>nul') do (
    docker rm -f %%i 2>nul
)
echo   [OK] Stray containers removed

REM Step 3: Remove shared Docker network
echo.
echo [Step 3/3] Removing Docker network...
docker network inspect flowcore_flowcore-net >nul 2>&1
if not errorlevel 1 (
    docker network rm flowcore_flowcore-net >nul 2>&1 && echo   [OK] Network removed || echo   [!] Could not remove network
) else (
    echo   Network flowcore_flowcore-net not found -- already gone
)

REM Optional: purge images
if %PURGE_IMAGES%==1 (
    echo.
    echo Purging locally-built FlowCore images...
    for %%I in (flowcore/platform:local flowcore/agents:local flowcore/api-ui:local flowcore/synthetic-replay:local) do (
        docker rmi %%I 2>nul && echo   [OK] Removed %%I || echo   [!] %%I not found
    )
)

echo.
echo ======================================================
echo   Destroy Complete
echo ======================================================
echo All FlowCore data, containers, and volumes have been removed.
echo.
echo To rebuild from scratch:
echo   .\scripts\rebuild.sh              -- full rebuild + data generation
echo   .\scripts\stack.sh up             -- start stack (existing images)
echo   .\scripts\start-databases.bat     -- start databases only
echo.
