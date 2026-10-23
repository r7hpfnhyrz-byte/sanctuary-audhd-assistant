#!/usr/bin/env bash
set -e

export PATH="/Users/student/.nvm/versions/node/v24.14.0/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
APP_DIR="/Users/student/Library/CloudStorage/GoogleDrive-robknightstrong@gmail.com/My Drive/AuDHD-Assistant"
cd "$APP_DIR"

echo "🚂 Step 1: Logging into Railway (your browser will open automatically)..."
npx --yes @railway/cli login

echo "🏗️ Step 2: Creating Railway project 'sanctuary-audhd-assistant'..."
npx --yes @railway/cli init --name "sanctuary-audhd-assistant" || true

echo "🔐 Step 3: Uploading live environment variables from .env..."
while IFS='=' read -r key val; do
    if [[ -n "$key" && ! "$key" =~ ^# ]]; then
        npx --yes @railway/cli variables --set "$key=$val"
    fi
done < .env

echo "🚀 Step 4: Deploying Sanctuary container to 24/7 Cloud..."
npx --yes @railway/cli up --detach

echo "🌐 Step 5: Generating public HTTPS domain..."
npx --yes @railway/cli domain || true

echo "✨ Deployment triggered! Run 'npx @railway/cli open' anytime to view your cloud dashboard."
