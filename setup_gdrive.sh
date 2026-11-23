#!/usr/bin/env bash
# FrimeRise — Conexão Rápida com Google Drive (Backup em Pastas Nomeadas + Economia de Disco)
# Usa rclone (MIT) para enviar automaticamente cada vídeo pronto para:
#   Google Drive -> FrimeRise / <Nome_do_Projeto>_<Data>_<ID>/
set -euo pipefail

echo "=================================================================="
echo "  FrimeRise — Conectar Google Drive (Pastas Nomeadas Automáticas)"
echo "=================================================================="
echo ""

# 1. Instalar rclone se não existir (preferindo ~/.local/bin sem precisar de sudo)
export PATH="$HOME/.local/bin:$PATH"
if ! command -v rclone >/dev/null 2>&1; then
  echo "[1/3] Instalando rclone (MIT) em ~/.local/bin/rclone..."
  mkdir -p "$HOME/.local/bin" /tmp/rclone_dl
  curl -fsSL "https://downloads.rclone.org/rclone-current-linux-amd64.zip" -o /tmp/rclone_dl/rclone.zip
  unzip -qo /tmp/rclone_dl/rclone.zip -d /tmp/rclone_dl
  cp /tmp/rclone_dl/rclone-*-linux-amd64/rclone "$HOME/.local/bin/rclone"
  chmod +x "$HOME/.local/bin/rclone"
  rm -rf /tmp/rclone_dl
else
  echo "[1/3] rclone já instalado: $(rclone version | head -n 1)"
fi

# 2. Verificar se já existe remote 'gdrive'
if rclone listremotes 2>/dev/null | grep -q "^gdrive:$"; then
  echo "[2/3] Remote 'gdrive:' já está configurado!"
else
  echo "[2/3] Abrindo login oficial do Google Drive no navegador..."
  echo "      → Faça login na sua conta Google e clique em Permitir."
  rclone config create gdrive drive scope=drive
fi

# 3. Criar pasta raiz FrimeRise/ e testar conexão
echo "[3/3] Criando pasta raiz 'FrimeRise/' no seu Google Drive..."
rclone mkdir gdrive:FrimeRise

echo ""
echo "=================================================================="
echo "  ✅ GOOGLE DRIVE CONECTADO AO FRIMERISE!"
echo "=================================================================="
echo "  • Pasta raiz: gdrive:FrimeRise/"
echo "  • Cada projeto será salvo em uma subpasta separada com o nome do tema."
echo "  • Para liberar espaço automático no SSD após cada upload, ative a caixa"
echo "    'Liberar espaço local após backup no Drive' na aba ⚙️ Setup do FrimeRise."
echo "=================================================================="
