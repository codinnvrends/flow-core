@echo off
REM =============================================================================
REM FlowCore — Build All Images (Windows)
REM
REM Rebuilds Docker images from source WITHOUT stopping containers or wiping data.
REM Use this after code changes when you want a fresh image build.
REM
REM To apply new images, restart the relevant containers after this:
REM   .\scripts\stack.sh restart platform
REM   .\scripts\stack.sh restart agents
REM   .\scripts\stack.sh restart api-ui
REM   .\scripts\stack.sh restart replay
REM
REM Usage:
REM   .\scripts\build-all.bat                  (rebuild all 4 images, no-cache)
REM   .\scripts\build-all.bat platform         (rebuild only platform)
REM   .\scripts\build-all.bat agents           (rebuild only agents)
REM   .\scripts\build-all.bat api-ui           (rebuild only api-ui incl. React)
REM   .\scripts\build-all.bat replay           (rebuild only replay)
REM   .\scripts\build-all.bat --with-cache     (use Docker layer cache, faster)
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "DOCKER_DIR=%PROJECT_ROOT%\docker"
set "ENV_FILE=%DOCKER_DIR%\.env"

set "F_STORES=%DOCKER_DIR%\docker-compose.yml"
set "F_KAFKA=%DOCKER_DIR%\docker-compose.kafka.yml"
set "F_PLATFORM=%DOCKER_DIR%\docker-compose.platform.yml"
set "F_AGENTS=%DOCKER_DIR%\docker-compose.agents.yml"
set "F_API=%DOCKER_DIR%\docker-compose.api.yml"
set "F_REPLAY=%DOCKER_DIR%\docker-compose.replay.yml"

REM Parse arguments
set "TARGET=all"
set "NO_CACHE=--no-cache"
set "CACHE_MSG=(no-cache)"

if not "%~1"=="" (
    if "%~1"=="--with-cache" (
        set "NO_CACHE="
        set "CACHE_MSG=(with-cache)"
    ) else (
        set "TARGET=%~1"
    )
)

if not "%~2"=="" (
    if "%~2"=="--with-cache" (
        set "NO_CACHE="
        set "CACHE_MSG=(with-cache)"
    )
)

REM Check Docker
docker info >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not running. Please start Docker first.
    exit /b 1
)

cd /d "%PROJECT_ROOT%"

REM Dispatch to build target
if "%TARGET%"=="all" goto build_all
if "%TARGET%"=="platform" goto build_platform
if "%TARGET%"=="agents" goto build_agents
if "%TARGET%"=="api-ui" goto build_api_ui
if "%TARGET%"=="apiui" goto build_api_ui
if "%TARGET%"=="api" goto build_api_ui
if "%TARGET%"=="ui" goto build_api_ui
if "%TARGET%"=="replay" goto build_replay
if "%TARGET%"=="synthetic-replay" goto build_replay

echo Error: Unknown target '%TARGET%'. Use: all ^| platform ^| agents ^| api-ui ^| replay
exit /b 1

:build_all
echo.
echo ======================================================
echo   FlowCore -- Build All Images %CACHE_MSG%
echo ======================================================
echo.
echo   NOTE: Running services will NOT be stopped.
echo   Restart containers after this to pick up new images.
echo.

call :do_build_platform
if errorlevel 1 exit /b 1

call :do_build_agents
if errorlevel 1 exit /b 1

call :do_build_api_ui
if errorlevel 1 exit /b 1

call :do_build_replay
if errorlevel 1 exit /b 1

echo.
echo ======================================================
echo   All Builds Complete
echo ======================================================
echo   Images built:
echo     flowcore/platform:local
echo     flowcore/agents:local
echo     flowcore/api-ui:local
echo     flowcore/synthetic-replay:local
echo.
echo   Next step -- restart containers to pick up new images:
echo     .\scripts\stack.sh restart platform
echo     .\scripts\stack.sh restart agents
echo     .\scripts\stack.sh restart api-ui
echo     .\scripts\stack.sh restart replay
echo.
exit /b 0

:build_platform
echo.
echo ======================================================
echo   Building: platform %CACHE_MSG%
echo ======================================================
call :do_build_platform
exit /b %ERRORLEVEL%

:build_agents
echo.
echo ======================================================
echo   Building: agents %CACHE_MSG%
echo ======================================================
call :do_build_agents
exit /b %ERRORLEVEL%

:build_api_ui
echo.
echo ======================================================
echo   Building: api-ui %CACHE_MSG% (includes React frontend)
echo ======================================================
call :do_build_api_ui
exit /b %ERRORLEVEL%

:build_replay
echo.
echo ======================================================
echo   Building: synthetic-replay %CACHE_MSG%
echo ======================================================
call :do_build_replay
exit /b %ERRORLEVEL%

REM =============================================================================
REM Build subroutines
REM =============================================================================

:do_build_platform
echo [platform] Building...
docker compose ^
    -f "%F_STORES%" -f "%F_KAFKA%" -f "%F_PLATFORM%" ^
    --env-file "%ENV_FILE%" ^
    build %NO_CACHE% platform
if errorlevel 1 (
    echo [FAIL] platform build failed
    exit /b 1
)
echo [OK] Platform image built -- flowcore/platform:local
goto :eof

:do_build_agents
echo [agents] Building...
docker compose ^
    -f "%F_STORES%" -f "%F_KAFKA%" -f "%F_PLATFORM%" -f "%F_AGENTS%" ^
    --env-file "%ENV_FILE%" ^
    build %NO_CACHE% agents
if errorlevel 1 (
    echo [FAIL] agents build failed
    exit /b 1
)
echo [OK] Agents image built -- flowcore/agents:local
goto :eof

:do_build_api_ui
echo [api-ui] Building (includes React frontend build)...
docker compose ^
    -f "%F_STORES%" -f "%F_KAFKA%" -f "%F_PLATFORM%" -f "%F_AGENTS%" -f "%F_API%" ^
    --env-file "%ENV_FILE%" ^
    build %NO_CACHE% api-ui
if errorlevel 1 (
    echo [FAIL] api-ui build failed
    exit /b 1
)
echo [OK] API+UI image built -- flowcore/api-ui:local
goto :eof

:do_build_replay
echo [synthetic-replay] Building...
docker compose ^
    -f "%F_STORES%" -f "%F_KAFKA%" -f "%F_REPLAY%" ^
    --env-file "%ENV_FILE%" ^
    build %NO_CACHE% synthetic-replay
if errorlevel 1 (
    echo [FAIL] synthetic-replay build failed
    exit /b 1
)
echo [OK] Replay image built -- flowcore/synthetic-replay:local
goto :eof
