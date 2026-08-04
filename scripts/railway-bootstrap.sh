#!/usr/bin/env bash
# Railway bootstrap + deploy (docs/deployment-plan.md). Rerunnable end to end — every
# step is idempotent or tolerates already-exists. Requires: railway CLI >= 5.26, logged
# in (`railway login`), jq. Run from the repo root.
#
# This is the exact sequence that produced the live deployment. Railway has no
# declarative project/service creation, so it lives here; per-service build/deploy
# behavior lives in backend/railway.toml and frontend/railway.toml, versioned with
# the code.
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-checkout-pricing-engine}"
WORKSPACE="${WORKSPACE:-josie29's Projects}"
ENVIRONMENT="${ENVIRONMENT:-production}"

command -v railway >/dev/null || { echo "railway CLI not found — npm i -g @railway/cli"; exit 1; }
command -v jq >/dev/null || { echo "jq not found"; exit 1; }

echo "==> Project"
railway status >/dev/null 2>&1 || railway init --name "$PROJECT_NAME" --workspace "$WORKSPACE"
PROJECT_ID=$(railway status --json | jq -r .id)

echo "==> Services"
railway add --service api 2>/dev/null || echo "  api exists"
railway add --service web 2>/dev/null || echo "  web exists"

echo "==> Domains (created before first deploy so env wiring needs no redeploy)"
railway domain --service api >/dev/null 2>&1 || true
railway domain --service web >/dev/null 2>&1 || true
API_DOMAIN=$(railway domain --service api --json | jq -r '.domains[0]')
WEB_DOMAIN=$(railway domain --service web --json | jq -r '.domains[0]')
echo "  api: $API_DOMAIN"
echo "  web: $WEB_DOMAIN"

echo "==> Variables"
railway variables --service api --skip-deploys --set "CORS_ORIGINS=${WEB_DOMAIN}" >/dev/null
# VITE_API_BASE_URL is consumed at build time; NIXPACKS_NODE_VERSION pins Node >= 22
# (deps require it; Nixpacks defaults to 18); NIXPACKS_NO_CACHE avoids an EBUSY on the
# node_modules cache mount during `npm ci`.
railway variables --service web --skip-deploys \
  --set "VITE_API_BASE_URL=${API_DOMAIN}" \
  --set "NIXPACKS_NODE_VERSION=22" \
  --set "NIXPACKS_NO_CACHE=1" >/dev/null

echo "==> Deploy"
# `railway up` inside a monorepo uploads the git root regardless of cwd (and its PATH
# argument fails with "prefix not found"), which puts each service's railway.toml in a
# subdirectory where Railway can't see it. Workaround: stage each service into a clean
# temp dir outside the repo and deploy from there.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

rsync -a --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude .ruff_cache --exclude '*.egg-info' backend/ "$STAGE/api/"
rsync -a --exclude node_modules --exclude dist frontend/ "$STAGE/web/"

for SVC in api web; do
  echo "  deploying $SVC..."
  (cd "$STAGE/$SVC" && railway up -p "$PROJECT_ID" -e "$ENVIRONMENT" -s "$SVC" -d -y)
done

echo "==> Done"
echo "  api: $API_DOMAIN (healthcheck: ${API_DOMAIN}/health)"
echo "  web: $WEB_DOMAIN"
echo "Rerun this script to redeploy after changes. GitHub-integrated CD is optional on"
echo "top: set each service's Root Directory (backend/, frontend/) and repo link once"
echo "in the Railway dashboard — the only step the CLI cannot express."
