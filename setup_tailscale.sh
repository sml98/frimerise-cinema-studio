#!/usr/bin/env bash
# FrimeRise — Configuração 1-Clique do Tailscale (Acesso Privado HTTPS no Celular em 4G/5G)
# Nunca expõe na internet pública (usa `tailscale serve`, restrito apenas aos seus dispositivos).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================================="
echo "  FrimeRise — Acesso Privado no Celular via Tailscale (HTTPS)"
echo "=================================================================="
echo ""

# 1. Instalar Tailscale se ainda não existir
if ! command -v tailscale >/dev/null 2>&1; then
  echo "[1/4] Instalando Tailscale oficial no Ubuntu (pedirá sua senha sudo)..."
  curl -fsSL https://tailscale.com/install.sh | sh
else
  echo "[1/4] Tailscale já instalado: $(tailscale version | head -n 1)"
fi

# 2. Garantir serviço tailscaled ativo no boot
echo "[2/4] Ativando serviço tailscaled..."
sudo systemctl enable --now tailscaled

# 3. Autenticar esta máquina na sua conta Tailscale
echo "[3/4] Conectando este Acer Aspire 5 à sua rede privada Tailscale..."
if ! tailscale status >/dev/null 2>&1; then
  echo "      → Abra o link que aparecer abaixo e faça login com a mesma conta que usará no celular."
  sudo tailscale up
else
  echo "      → Já conectado ao Tailscale!"
fi

# 4. Ativar proxy HTTPS privado apontando para o FrimeRise local (127.0.0.1:8000)
# NOTA: `tailscale serve` é 100% PRIVADO (somente sua conta Tailscale acessa).
echo "[4/4] Configurando proxy HTTPS privado (porta 443 -> http://127.0.0.1:8000)..."
sudo tailscale serve --bg http://127.0.0.1:8000

echo ""
echo "=================================================================="
echo "  ✅ PRONTO! Seu FrimeRise está acessível no celular (4G/5G/Wi-Fi)"
echo "=================================================================="
TS_URL="$(tailscale status --json | "$DIR/.venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); n=(d.get("Self",{}).get("DNSName") or "").rstrip("."); print("https://"+n if n else "")' 2>/dev/null || true)"
TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"

if [ -n "$TS_URL" ]; then
  echo "  🔗 Link HTTPS Privado: $TS_URL"
fi
if [ -n "$TS_IP" ]; then
  echo "  🌐 IP Tailscale:       $TS_IP"
fi
echo ""
echo "  No seu celular:"
echo "    1. Instale o app oficial 'Tailscale' (Android Play Store ou iOS App Store)."
echo "    2. Entre com a MESMA conta usada agora e ligue a chave do Tailscale."
echo "    3. Abra o link HTTPS acima no navegador do celular e faça login no FrimeRise."
echo ""
echo "  Dica: Para evitar que o notebook durma quando você estiver fora:"
echo "    ./start_frimerise.sh --keep-awake"
echo "  Para desligar o acesso remoto quando quiser:"
echo "    sudo tailscale serve reset"
echo "=================================================================="
