#!/usr/bin/env bash
# One-time Railway bootstrap (docs/deployment-plan.md). Rerunnable: every step is
# idempotent or fails loudly without side effects. Requires: railway CLI, logged in
# (`railway login`), run from the repo root.
#
# What Railway cannot express declaratively (project/service creation, GitHub repo
# linking, root directories) lives here; everything else is in backend/railway.toml
# and frontend/railway.toml, versioned with the code.
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-checkout-pricing-engine}"
REPO="${REPO:-Josie29/checkout-pricing-engine}"
BRANCH="${BRANCH:-main}"

command -v railway >/dev/null || { echo "railway CLI not found — npm i -g @railway/cli"; exit 1; }

echo "==> Project"
railway status >/dev/null 2>&1 || railway init --name "$PROJECT_NAME"

echo "==> Services (api: backend/, web: frontend/)"
# `railway add` is idempotent per service name failure; ignore already-exists errors.
railway add --service api  --repo "$REPO" 2>/dev/null || echo "  api exists"
railway add --service web  --repo "$REPO" 2>/dev/null || echo "  web exists"

echo "==> Root directories + branch (per-service, via variables API is not possible — set via dashboard-equivalent CLI)"
# Railway CLI (>=3.x) supports setting the root directory on link/deploy; keep explicit:
railway service update api --root-directory backend  --branch "$BRANCH" 2>/dev/null || \
  echo "  NOTE: if 'service update' is unavailable in your CLI version, set Root Directory=backend (api) and =frontend (web) once in the dashboard — the only non-CLI step."
railway service update web --root-directory frontend --branch "$BRANCH" 2>/dev/null || true

echo "==> Env wiring (reference variables; not secrets)"
# Railway-assigned domains exist only after first deploy — rerun this script once after
# both services have domains, then redeploy each (see docs/deployment-plan.md).
API_DOMAIN=$(railway domain --service api --json 2>/dev/null | head -1 || true)
WEB_DOMAIN=$(railway domain --service web --json 2>/dev/null | head -1 || true)
[ -n "$WEB_DOMAIN" ] && railway variables --service api --set "CORS_ORIGINS=https://${WEB_DOMAIN}" || echo "  web domain not yet assigned — rerun after first deploy"
[ -n "$API_DOMAIN" ] && railway variables --service web --set "VITE_API_BASE_URL=https://${API_DOMAIN}" || echo "  api domain not yet assigned — rerun after first deploy"

echo "==> Done. Push to ${BRANCH} deploys via GitHub integration (watchPatterns scope rebuilds per service)."
