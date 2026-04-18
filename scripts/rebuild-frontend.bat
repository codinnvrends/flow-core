@echo off
REM =============================================================================
REM FlowCore — Rebuild Frontend (Windows)
REM
REM Shortcut for rebuilding the api-ui image (React frontend + nginx + API services).
REM Delegates entirely to rebuild.sh api-ui.
REM
REM Usage:
REM   .\scripts\rebuild-frontend.bat               (no-cache build + recreate container)
REM   .\scripts\rebuild-frontend.bat --with-cache  (faster rebuild using layer cache)
REM =============================================================================

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%rebuild.sh" api-ui %*
