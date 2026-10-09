
# Aliases para repositórios RH
alias rh-frontend='cd /Users/vini/Desktop/www/rh/f2-rh-app'
alias rh-backend='cd /Users/vini/Desktop/www/rh/f2-rh-api'
alias rh-pull-all='cd /Users/vini/Desktop/www/rh && ./git-all.sh pull'
alias rh-push-all='cd /Users/vini/Desktop/www/rh && ./git-all.sh push'
alias rh-status-all='cd /Users/vini/Desktop/www/rh && ./git-all.sh status'

export PATH="$HOME/.local/bin:$PATH"
export PATH=$PATH:$HOME/.maestro/bin

# bun completions
[ -s "/Users/vini/.bun/_bun" ] && source "/Users/vini/.bun/_bun"

# bun
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"

# Dotfiles aliases
[ -f ~/dotfiles/shell/.aliases ] && source ~/dotfiles/shell/.aliases

## [Completion]
## Completion scripts setup. Remove the following line to uninstall
[[ -f /Users/vini/.dart-cli-completion/zsh-config.zsh ]] && . /Users/vini/.dart-cli-completion/zsh-config.zsh || true
## [/Completion]


# Android SDK
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

# === GitHub Actions self-hosted runner ===
alias runneron='[ -f "$HOME/Library/LaunchAgents/actions.runner.momease-mom-ease.mac-local-prod.plist" ] && launchctl load "$HOME/Library/LaunchAgents/actions.runner.momease-mom-ease.mac-local-prod.plist" 2>/dev/null; echo "✓ actions runner ON"'
alias runneroff='[ -f "$HOME/Library/LaunchAgents/actions.runner.momease-mom-ease.mac-local-prod.plist" ] && launchctl unload "$HOME/Library/LaunchAgents/actions.runner.momease-mom-ease.mac-local-prod.plist" 2>/dev/null; echo "✓ actions runner OFF"'
alias devon='runneron'
alias devoff='runneroff'

# Local-only env (Kotic prod PAT, etc). File is chmod 600 and not in dotfiles repo.
[ -f ~/.kotic-env ] && source ~/.kotic-env

# === dev CLI QoL (adicionado por Claude 2026-06; remover o bloco reverte) ===
eval "$(zoxide init zsh)"                          # z <dir>: pula pros diretorios mais usados
command -v fzf >/dev/null 2>&1 && source <(fzf --zsh) 2>/dev/null  # Ctrl-T arquivos, Alt-C cd
eval "$(atuin init zsh --disable-up-arrow)"        # Ctrl-R: busca no historico (atuin vence o fzf)
alias ls='eza --group-directories-first'
alias ll='eza -la --git --group-directories-first'
alias lt='eza --tree --level=2 --git-ignore'
alias lg='lazygit'

# Chaos/Kotic PAT — lido do Keychain, nunca hardcoded (usado pelo MCP kotic no .mcp.json)
export CHAOS_PAT=$(security find-generic-password -s chaos-pat -w ~/Library/Keychains/login.keychain-db 2>/dev/null)

# Atrium
export ATRIUM_CODEX_TOKEN=atr_4702b6e7dc8841e5b004a069dc7bc2c7a2099703c27d426bb5f371b204c612b5

# Claude Code: limpa marker de child-session herdado por apps lancados de dentro
# de uma sessao (ex: AeroSpace -> Ghostty). Com o marker setado o CLI nao grava
# transcript. Shells nao interativos (claude -p real child) nao leem este arquivo,
# entao child sessions legitimas continuam sem gravar. Remover a linha reverte.
unset CLAUDE_CODE_CHILD_SESSION

# Added by cua-driver-rs installer — see https://github.com/trycua/cua
export PATH="/Users/vini/.local/bin:$PATH"
eval "$(mise activate zsh)"

# ~/bin (launcher j3ultimate)
export PATH="$HOME/bin:$PATH"

# ferramentas locais (memguard, heavy-run)
export PATH="$HOME/dotfiles/bin:$PATH"

# CX53: entra direto na sessão tmux persistente
cx()  { mosh cx53ts -- .local/bin/work "${1:-home}"; }   # VPS via mosh+Tailscale; cx minecraft
cxs() { ssh -t cx53ts .local/bin/work "${1:-home}"; }   # fallback ssh
alias mc="cx minecraft"

# CX: escolha compartilhada de agente
source "$HOME/Developer/cx-harness/mac-shell.zsh"
