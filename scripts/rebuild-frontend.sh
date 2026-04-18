#!/usr/bin/env bash
# =============================================================================
# FlowCore — Rebuild Frontend (Linux/Mac)
#
# Shortcut for rebuilding the api-ui image (React frontend + nginx + API services).
# Delegates entirely to rebuild.sh api-ui.
#
# Usage:
#   ./scripts/rebuild-frontend.sh               # no-cache build + recreate container
#   ./scripts/rebuild-frontend.sh --with-cache  # faster rebuild using layer cache
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/rebuild.sh" api-ui "$@"
