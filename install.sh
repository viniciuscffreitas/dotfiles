#!/usr/bin/env bash
set -e

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Dotfiles install: $DOTFILES_DIR"
echo "==> HOME: $HOME"

# Detectar OS
OS="$(uname -s)"
case "$OS" in
  Darwin) echo "==> OS: macOS" ;;
  Linux)  echo "==> OS: Linux/WSL2" ;;
  *)      echo "WARN: OS não reconhecido: $OS" ;;
esac

# --- Claude Code ---
echo ""
echo "--- Configurando ~/.claude ---"

if [ -L "$HOME/.claude" ]; then
  echo "  symlink ~/.claude já existe, pulando"
elif [ -d "$HOME/.claude" ]; then
  echo "  AVISO: ~/.claude é um diretório real. Fazendo backup..."
  mv "$HOME/.claude" "$HOME/.claude.backup.$(date +%Y%m%d%H%M%S)"
  ln -sf "$DOTFILES_DIR/claude" "$HOME/.claude"
  echo "  symlink criado: ~/.claude -> $DOTFILES_DIR/claude"
else
  ln -sf "$DOTFILES_DIR/claude" "$HOME/.claude"
  echo "  symlink criado: ~/.claude -> $DOTFILES_DIR/claude"
fi

# Recriar diretórios locais excluídos do repo
for dir in memory cache sessions statsig downloads paste-cache debug telemetry todos tasks ide ccline; do
  mkdir -p "$HOME/.claude/$dir"
done
mkdir -p "$HOME/.claude/plugins/cache"
echo "  diretórios locais criados"

# Gerar settings.json a partir do template
if [ -f "$DOTFILES_DIR/claude/settings.template.json" ]; then
  sed "s|__HOME__|$HOME|g" "$DOTFILES_DIR/claude/settings.template.json" > "$HOME/.claude/settings.json"
  echo "  settings.json gerado para $HOME"
else
  echo "  WARN: settings.template.json não encontrado"
fi

# --- Shell ---
echo ""
echo "--- Configurando shell ---"

# .zshrc
if [ -f "$HOME/.zshrc" ] && [ ! -L "$HOME/.zshrc" ]; then
  cp "$HOME/.zshrc" "$HOME/.zshrc.backup.$(date +%Y%m%d%H%M%S)"
fi
ln -sf "$DOTFILES_DIR/shell/.zshrc" "$HOME/.zshrc"
echo "  symlink criado: ~/.zshrc"

# .bashrc (opcional)
if [ -f "$DOTFILES_DIR/shell/.bashrc" ]; then
  if [ -f "$HOME/.bashrc" ] && [ ! -L "$HOME/.bashrc" ]; then
    cp "$HOME/.bashrc" "$HOME/.bashrc.backup.$(date +%Y%m%d%H%M%S)"
  fi
  ln -sf "$DOTFILES_DIR/shell/.bashrc" "$HOME/.bashrc"
  echo "  symlink criado: ~/.bashrc"
fi

echo ""
echo "==> Instalação concluída!"
echo "    Execute 'source ~/.zshrc' para recarregar o shell."
