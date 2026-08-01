#!/usr/bin/env bash
set -e

echo "=== AI Data Store Setup ==="

# Check dependencies
if ! command -v docker &>/dev/null; then
    echo "Error: Docker is not installed." >&2
    exit 1
fi
if ! docker compose version &>/dev/null; then
    echo "Error: Docker Compose is not available." >&2
    exit 1
fi

# Create .env if it doesn't exist
if [ -f .env ]; then
    echo "✓ .env already exists, skipping key generation"
else
    API_KEY=$(openssl rand -hex 32)
    UI_PASSWORD=$(openssl rand -hex 16)
    cat > .env <<EOF
API_KEY=${API_KEY}
UI_USERNAME=admin
UI_PASSWORD=${UI_PASSWORD}
EOF
    echo "✓ Generated .env with new API key and dashboard credentials"
fi

# Build and start
echo "Building and starting containers..."
docker compose up -d --build

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Server running at: http://$(hostname -I | awk '{print $1}'):8742/sse"
echo "API key:           $(grep API_KEY .env | cut -d= -f2)"
echo ""
echo "Dashboard:         http://$(hostname -I | awk '{print $1}'):8743"
echo "Dashboard login:   $(grep UI_USERNAME .env | cut -d= -f2) / $(grep UI_PASSWORD .env | cut -d= -f2)"
echo ""
echo "Save that API key — you will need it to connect from your laptop."
