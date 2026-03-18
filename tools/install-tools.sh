#!/usr/bin/env bash
# Instala ferramentas de desenvolvimento por OS
set -e

OS="$(uname -s)"

install_mac() {
  echo "==> Instalando ferramentas macOS via Homebrew"

  # Instalar Homebrew se não existir
  if ! command -v brew &>/dev/null; then
    echo "  Instalando Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi

  brew install git node python3 gh
  brew install --cask visual-studio-code

  echo "  macOS tools instaladas"
}

install_linux() {
  echo "==> Instalando ferramentas Linux/WSL2 via apt"
  sudo apt-get update -qq
  sudo apt-get install -y git curl wget unzip build-essential python3 python3-pip nodejs npm

  # GitHub CLI
  if ! command -v gh &>/dev/null; then
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update && sudo apt install gh -y
  fi

  echo "  Linux/WSL2 tools instaladas"
}

case "$OS" in
  Darwin) install_mac ;;
  Linux)  install_linux ;;
  *)      echo "OS não suportado: $OS"; exit 1 ;;
esac

echo ""
echo "==> Ferramentas instaladas com sucesso!"
