#!/usr/bin/env bash
# macOS defaults — UX/DX tweaks (macOS 26 Tahoe)
# Idempotent. Revert: see macos-defaults-backup-*.txt ao lado, ou `defaults delete <domain> <key>`.
# KeyRepeat/InitialKeyRepeat exigem logout/login para valer.

set -uo pipefail

BACKUP="$(dirname "$0")/macos-defaults-backup-$(date +%Y%m%d).txt"

backup() {
  local domain="$1" key="$2"
  printf '%s %s = %s\n' "$domain" "$key" "$(defaults read "$domain" "$key" 2>/dev/null || echo '<unset>')" >> "$BACKUP"
}

w() {
  local domain="$1" key="$2"; shift 2
  backup "$domain" "$key"
  defaults write "$domain" "$key" "$@"
}

### Keyboard — DX
w NSGlobalDomain KeyRepeat -int 2                              # repeat rápido (mínimo do UI é 2; 1 = ainda mais rápido)
w NSGlobalDomain InitialKeyRepeat -int 15                      # delay curto até começar o repeat
w NSGlobalDomain ApplePressAndHoldEnabled -bool false          # segurar tecla repete em vez de abrir menu de acentos
w NSGlobalDomain NSAutomaticCapitalizationEnabled -bool false
w NSGlobalDomain NSAutomaticDashSubstitutionEnabled -bool false
w NSGlobalDomain NSAutomaticPeriodSubstitutionEnabled -bool false
w NSGlobalDomain NSAutomaticQuoteSubstitutionEnabled -bool false   # smart quotes quebram código colado
w NSGlobalDomain NSAutomaticSpellingCorrectionEnabled -bool false
w NSGlobalDomain AppleKeyboardUIMode -int 2                    # Tab navega todos os controles em dialogs

### Finder
w NSGlobalDomain AppleShowAllExtensions -bool true
w com.apple.finder AppleShowAllFiles -bool true                # mostra dotfiles (toggle: Cmd+Shift+.)
w com.apple.finder ShowPathbar -bool true
w com.apple.finder ShowStatusBar -bool true
w com.apple.finder FXPreferredViewStyle -string "Nlsv"         # list view por default
w com.apple.finder _FXSortFoldersFirst -bool true
w com.apple.finder FXDefaultSearchScope -string "SCcf"         # busca na pasta atual, não no Mac inteiro
w com.apple.finder FXEnableExtensionChangeWarning -bool false
w com.apple.finder NewWindowTarget -string "PfHm"              # janela nova abre na home
w com.apple.finder NewWindowTargetPath -string "file://${HOME}/"
w com.apple.finder FXRemoveOldTrashItems -bool true            # lixeira auto-esvazia itens >30 dias
w com.apple.desktopservices DSDontWriteNetworkStores -bool true   # sem .DS_Store em rede
w com.apple.desktopservices DSDontWriteUSBStores -bool true       # sem .DS_Store em USB

### Save/print dialogs sempre expandidos
w NSGlobalDomain NSNavPanelExpandedStateForSaveMode -bool true
w NSGlobalDomain NSNavPanelExpandedStateForSaveMode2 -bool true
w NSGlobalDomain PMPrintingExpandedStateForPrint -bool true
w NSGlobalDomain PMPrintingExpandedStateForPrint2 -bool true

### Dock + Spaces
w com.apple.dock autohide -bool true
w com.apple.dock autohide-delay -float 0
w com.apple.dock autohide-time-modifier -float 0.15
w com.apple.dock show-recents -bool false
w com.apple.dock minimize-to-application -bool true
w com.apple.dock mru-spaces -bool false                        # Spaces não se reordenam sozinhos

### Animações mais rápidas
w NSGlobalDomain NSWindowResizeTime -float 0.001
w NSGlobalDomain NSAutomaticWindowAnimationsEnabled -bool false

### Screenshots
mkdir -p "${HOME}/Screenshots"
w com.apple.screencapture location -string "${HOME}/Screenshots"
w com.apple.screencapture disable-shadow -bool true

### TextEdit — plain text por default
w com.apple.TextEdit RichText -int 0
w com.apple.TextEdit SmartQuotes -bool false

### Dev tools
w com.apple.dt.Xcode ShowBuildOperationDuration -bool true     # tempo de build na toolbar do Xcode
w com.apple.Safari ShowFullURLInSmartSearchField -bool true || true  # falha sem Full Disk Access; ok ignorar

### Activity Monitor — refresh 2s
w com.apple.ActivityMonitor UpdatePeriod -int 2

### Performance / anti-annoyance
w com.apple.WindowManager EnableStandardClickToShowDesktop -bool false  # clicar no wallpaper não esconde janelas
w com.apple.universalaccess reduceTransparency -bool true               # alivia WindowServer; revert: -bool false

killall Dock Finder SystemUIServer 2>/dev/null || true
echo "OK. Backup dos valores anteriores: $BACKUP"
echo "KeyRepeat só aplica após logout/login."
