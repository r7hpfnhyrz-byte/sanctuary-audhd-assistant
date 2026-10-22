#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${1:-sanctuary-audhd-assistant}"
REGION="${2:-europe-west2}"

echo "🚀 Deploying Sanctuary AuDHD Personal Assistant to Google Cloud Run ($REGION)..."
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8765
