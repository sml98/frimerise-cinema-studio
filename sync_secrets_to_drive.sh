#!/usr/bin/env bash
# Sincroniza data/frimerise.db (e opcionalmente a sessão do Google Flow Pro)
# para uma pasta PRIVADA no seu Google Drive (gdrive:FrimeRise_Secrets/)
# usando backup atômico SQLite (WAL-safe). NUNCA sobe nada no GitHub!
#
# Uso:
#   ./sync_secrets_to_drive.sh              # envia apenas frimerise.db (~700 KB)
#   ./sync_secrets_to_drive.sh --with-flow  # envia frimerise.db + sessão Flow Pro (sem caches)

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

REMOTE="${FRIMERISE_GDRIVE_REMOTE:-gdrive}"
SECRETS_FOLDER="${FRIMERISE_SECRETS_FOLDER:-FrimeRise_Secrets}"
WITH_FLOW=0
for arg in "$@"; do
  if [ "$arg" = "--with-flow" ]; then
    WITH_FLOW=1
  fi
done

if ! command -v rclone >/dev/null 2>&1; then
  echo "❌ rclone não encontrado. Execute ./setup_gdrive.sh primeiro." >&2
  exit 1
fi

if [ ! -f "$DIR/data/frimerise.db" ]; then
  echo "❌ $DIR/data/frimerise.db não encontrado." >&2
  exit 1
fi

TMP_DIR="$(mktemp -d /tmp/frimerise_secrets_XXXXXX)"
chmod 700 "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

SNAP_DB="$TMP_DIR/frimerise.db"
echo "🔒 Criando snapshot consistente (WAL-safe) de data/frimerise.db..."
"$DIR/.venv/bin/python" - "$DIR/data/frimerise.db" "$SNAP_DB" <<'PY'
import os, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dst)
with d:
    s.backup(d)
d.close()
s.close()
os.chmod(dst, 0o600)
PY

echo "☁️  Enviando para ${REMOTE}:${SECRETS_FOLDER}/frimerise.db..."
rclone mkdir "${REMOTE}:${SECRETS_FOLDER}"
rclone copyto "$SNAP_DB" "${REMOTE}:${SECRETS_FOLDER}/frimerise.db" --progress

if [ "$WITH_FLOW" -eq 1 ] && [ -d "$DIR/data/profiles/google_flow_pro" ]; then
  FLOW_TAR="$TMP_DIR/google_flow_pro.tar.gz"
  echo "🌊 Empacotando sessão Google Flow Pro (ignorando caches pesados do Chromium)..."
  tar -czf "$FLOW_TAR" \
    --exclude='Cache' \
    --exclude='Code Cache' \
    --exclude='GPUCache' \
    --exclude='GrShaderCache' \
    --exclude='ShaderCache' \
    --exclude='Service Worker/CacheStorage' \
    --exclude='Crashpad' \
    -C "$DIR/data/profiles" google_flow_pro
  chmod 600 "$FLOW_TAR"
  echo "☁️  Enviando sessão Flow Pro para ${REMOTE}:${SECRETS_FOLDER}/google_flow_pro.tar.gz..."
  rclone copyto "$FLOW_TAR" "${REMOTE}:${SECRETS_FOLDER}/google_flow_pro.tar.gz" --progress
fi

echo "✅ Pronto! Suas credenciais privadas estão seguras em Meu Drive/${SECRETS_FOLDER}/ (fora do GitHub)."
