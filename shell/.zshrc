
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
