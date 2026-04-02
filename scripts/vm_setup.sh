#!/usr/bin/env bash
# One-shot bootstrap for a fresh Ubuntu 22.04 / 24.04 LTS VM.
# Run as root or with sudo: bash scripts/vm_setup.sh
set -euo pipefail

echo "==> Installing Docker..."
apt-get update -y
apt-get install -y --no-install-recommends \
    docker.io \
    docker-compose-plugin \
    git \
    curl

echo "==> Enabling Docker service..."
systemctl enable --now docker

echo "==> Adding current user to docker group..."
if [ "${SUDO_USER:-}" != "" ]; then
    usermod -aG docker "$SUDO_USER"
    echo "    Added $SUDO_USER to docker group."
    echo "    Log out and back in for group membership to take effect."
else
    echo "    Note: running as root, no additional user to add to docker group."
fi

echo ""
echo "Setup complete! Next steps:"
echo "  git clone <your-repo-url> polara_quant"
echo "  cd polara_quant"
echo "  docker compose up -d"
echo "  curl http://localhost:8000/health"
