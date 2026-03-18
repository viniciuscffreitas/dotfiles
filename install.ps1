# install.ps1 — Bootstrap Windows para usar dotfiles via WSL2
# Executa no PowerShell como Administrador

Write-Host "==> Dotfiles Bootstrap (Windows)" -ForegroundColor Cyan

# Instalar WSL2 com Ubuntu
Write-Host ""
Write-Host "--- Instalando WSL2 ---"
wsl --install -d Ubuntu

Write-Host ""
Write-Host "--- Instalando ferramentas nativas ---"

# Verificar se winget está disponível
if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Git.Git
    winget install -e --id Microsoft.WindowsTerminal
    winget install -e --id Microsoft.VisualStudioCode
    Write-Host "  Ferramentas instaladas via winget"
} else {
    Write-Host "  WARN: winget nao encontrado. Instale manualmente:"
    Write-Host "    - Git for Windows: https://git-scm.com/download/win"
    Write-Host "    - Windows Terminal: Microsoft Store"
}

Write-Host ""
Write-Host "==> Proximo passo:" -ForegroundColor Green
Write-Host "    1. Reinicie o Windows para completar a instalacao do WSL2"
Write-Host "    2. Abra o Ubuntu no Windows Terminal"
Write-Host "    3. Execute dentro do WSL2:"
Write-Host "       git clone https://github.com/SEU_USER/dotfiles ~/dotfiles"
Write-Host "       bash ~/dotfiles/install.sh"
Write-Host "       source ~/.zshrc"
