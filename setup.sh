#!/bin/bash
# Run this on your DigitalOcean Droplet as the 'pa' user
# Usage: bash setup.sh
set -e

echo "==> Updating system packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ffmpeg python3.11 python3-pip python3.11-venv build-essential

echo "==> Installing Node.js 22..."
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

echo "==> Installing OpenClaw..."
sudo npm install -g openclaw@latest

echo "==> Setting up Python virtual environment..."
cd ~/pa
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "==> Making scripts executable..."
chmod +x scripts/transcribe.sh

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env and fill in your API keys"
echo "  2. Run: openclaw onboard --auth-choice openrouter-api-key"
echo "  3. Run: openclaw auth google"
