#!/usr/bin/env bash
# render_colab.sh — Render do episódio Natal numa sessão Colab persistente.
#
# Fluxo: acha o frimerise.db preenchido -> abre sessão 'frime' na GPU -> sobe
# script + banco + config do rclone -> renderiza com narração -> instala rclone
# no Colab e envia o MP4 para FrimeRise_Exports/ no Google Drive -> encerra a VM
# (trap EXIT, nunca fica sessão ligada consumindo cota).
#
# Uso:  ./render_colab.sh
# Variáveis opcionais: COLAB_SESSION, COLAB_GPU, SPEC, OUT, FRIMERISE_DB
set -Eeuo pipefail

SESSION="${COLAB_SESSION:-frime}"
GPU="${COLAB_GPU:-L4}"
GPU_FALLBACK="${COLAB_GPU_FALLBACK:-T4}"
SPEC="${SPEC:-data/natal_verdadeiro.json}"
OUT="${OUT:-natal_verdadeiro.mp4}"
DRIVE_REMOTE="${DRIVE_REMOTE:-gdrive}"
DRIVE_FOLDER="${DRIVE_FOLDER:-FrimeRise_Exports}"
RCLONE_CFG="$HOME/.config/rclone/rclone.conf"

c_info=$'\033[1;36m'; c_ok=$'\033[1;32m'; c_err=$'\033[1;31m'; c_off=$'\033[0m'
log()  { printf '%s[render_colab]%s %s\n' "$c_info" "$c_off" "$*"; }
ok()   { printf '%s[render_colab]%s %s\n' "$c_ok"   "$c_off" "$*"; }
die()  { printf '%s[render_colab] ERRO:%s %s\n' "$c_err" "$c_off" "$*" >&2; exit 1; }

cd "$(dirname "$0")"
REPO_DIR="$PWD"

# ---------------------------------------------------------------------------
# 1) Achar o frimerise.db PREENCHIDO (tabela settings + gemini_api_key válida)
# ---------------------------------------------------------------------------
db_is_valid() {
  [[ -n "${1:-}" && -f "$1" ]] || return 1
  python3 - "$1" <<'PY' >/dev/null 2>&1
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
if "settings" not in tables:
    sys.exit(1)
row = db.execute("SELECT value FROM settings WHERE key='gemini_api_key'").fetchone()
if not row or not row[0] or len(str(row[0])) < 20:
    sys.exit(1)
sys.exit(0)
PY
}

log "procurando frimerise.db preenchido..."
DB=""
for cand in "${FRIMERISE_DB:-}" "data/frimerise.db" "$HOME/.frimerise/frimerise.db" \
            "$HOME/.local/share/frimerise/frimerise.db"; do
  [[ -n "$cand" ]] || continue
  if db_is_valid "$cand"; then DB="$cand"; break; fi
  [[ -f "${cand:-/nonexistent}" ]] && log "  ignorado (sem tabela settings ou sem gemini_api_key): $cand"
done
[[ -n "$DB" ]] || die "nenhum frimerise.db preenchido encontrado (defina FRIMERISE_DB=/caminho)"
ok "banco válido: $DB ($(stat -c%s "$DB") bytes)"

[[ -f "$REPO_DIR/colab_run_lemo.py" ]] || die "colab_run_lemo.py não encontrado em $REPO_DIR"
[[ -f "$REPO_DIR/$SPEC" ]]            || die "spec não encontrado: $SPEC"
[[ -f "$RCLONE_CFG" ]]                || die "rclone não configurado ($RCLONE_CFG). Rode ./setup_gdrive.sh"

# ---------------------------------------------------------------------------
# 2) Sessão Colab + trap de encerramento (nunca deixar VM ligada)
# ---------------------------------------------------------------------------
cleanup() {
  local rc=$?
  log "encerrando sessão '$SESSION' (trap EXIT)..."
  colab stop -s "$SESSION" >/dev/null 2>&1 || log "  aviso: colab stop falhou"
  exit $rc
}
trap cleanup EXIT INT TERM

log "criando sessão '$SESSION' na GPU $GPU"
if ! colab new -s "$SESSION" --gpu "$GPU"; then
  log "GPU $GPU indisponível — tentando $GPU_FALLBACK"
  colab new -s "$SESSION" --gpu "$GPU_FALLBACK" || die "não foi possível criar a sessão (verifique 'colab sessions' / login)"
fi
ok "sessão '$SESSION' ativa"

# ---------------------------------------------------------------------------
# 3) Uploads para /content/
# ---------------------------------------------------------------------------
log "enviando colab_run_lemo.py, frimerise.db e rclone.conf para /content/"
colab upload -s "$SESSION" "$REPO_DIR/colab_run_lemo.py" /content/colab_run_lemo.py
colab upload -s "$SESSION" "$DB"                         /content/frimerise.db
colab upload -s "$SESSION" "$RCLONE_CFG"                 /content/rclone.conf
ok "uploads concluídos"
colab ls -s "$SESSION" /content/ || true

# ---------------------------------------------------------------------------
# 4) Execução do render
#    `colab exec -f` roda o arquivo mas NÃO repassa argv -> o argparse do runner
#    quebraria. Por isso mandamos código por stdin chamando o script via
#    subprocess, com --timeout 0 (render longo, sem limite de silêncio).
#    O banco é copiado para FrimeRise_Secrets fake + repo/data, que é onde o
#    runner realmente o procura (sync_secrets_and_load_keys).
# ---------------------------------------------------------------------------
log "renderizando $SPEC na sessão '$SESSION' (pode levar 20-40 min)..."
colab exec -s "$SESSION" --timeout 0 <<PY
import os, shutil, subprocess, sys

# Drive "montado" como diretório comum: evita o drive.mount() interativo, que
# travaria um exec não-interativo esperando autorização no navegador.
secrets = '/content/drive/MyDrive/FrimeRise_Secrets'
exports = '/content/drive/MyDrive/FrimeRise_Exports'
os.makedirs(secrets, exist_ok=True)
os.makedirs(exports, exist_ok=True)
shutil.copy2('/content/frimerise.db', secrets + '/frimerise.db')

repo = '/content/frimerise-cinema-studio'
if os.path.isdir(repo):
    subprocess.run(['git', '-C', repo, 'pull', '--ff-only', 'origin', 'main'], check=False)
else:
    subprocess.run(['git', 'clone', '--depth', '1',
                    'https://github.com/sml98/frimerise-cinema-studio.git', repo], check=True)
os.makedirs(repo + '/data', exist_ok=True)
shutil.copy2('/content/frimerise.db', repo + '/data/frimerise.db')

cmd = [sys.executable, '/content/colab_run_lemo.py',
       '--mode', 'frimerise', '--spec', '${SPEC}', '--output', '${OUT}']
print('[render_colab] executando:', ' '.join(cmd), flush=True)
rc = subprocess.run(cmd, cwd=repo).returncode
print('[render_colab] retorno do runner:', rc, flush=True)
if rc != 0:
    raise SystemExit(rc)
PY
ok "render finalizado"

# ---------------------------------------------------------------------------
# 5) rclone no Colab + envio para o Drive
# ---------------------------------------------------------------------------
log "instalando rclone no Colab e enviando para $DRIVE_REMOTE:$DRIVE_FOLDER"
colab exec -s "$SESSION" --timeout 0 <<PY
import os, subprocess, sys

def sh(cmd):
    return subprocess.run(cmd, shell=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout

if not sh('command -v rclone').strip():
    print('[render_colab] instalando rclone...', flush=True)
    out = sh('apt-get -qq update >/dev/null 2>&1; apt-get -qq install -y rclone 2>&1 | tail -3')
    print(out, flush=True)
    if not sh('command -v rclone').strip():
        print('[render_colab] apt falhou; usando install.sh oficial', flush=True)
        print(sh('curl -fsSL https://rclone.org/install.sh | bash 2>&1 | tail -5'), flush=True)

if not sh('command -v rclone').strip():
    print('[render_colab] ERRO: rclone não pôde ser instalado', flush=True)
    raise SystemExit(1)
print('[render_colab] rclone:', sh('rclone version | head -1').strip(), flush=True)

cands = ['/content/exports/${OUT}',
         '/content/drive/MyDrive/FrimeRise_Exports/${OUT}',
         '/content/${OUT}']
src = next((p for p in cands if os.path.exists(p)), None)
if not src:
    print('[render_colab] ERRO: MP4 não encontrado. Procurado em:', cands, flush=True)
    raise SystemExit(1)
print('[render_colab] enviando', src, '->', '${DRIVE_REMOTE}:${DRIVE_FOLDER}/${OUT}', flush=True)

rc = subprocess.run(['rclone', '--config', '/content/rclone.conf', '--stats-one-line',
                     'copyto', src, '${DRIVE_REMOTE}:${DRIVE_FOLDER}/${OUT}']).returncode
print('[render_colab] rclone retorno:', rc, flush=True)
if rc != 0:
    raise SystemExit(rc)
print('[render_colab] OK -> Meu Drive/${DRIVE_FOLDER}/${OUT}', flush=True)
PY
ok "arquivo enviado para Meu Drive/$DRIVE_FOLDER/$OUT"

# Verificação final do lado local (rclone do host é read-only no token refresh,
# então não tratamos falha aqui como erro fatal).
log "conferindo no Drive (a partir desta máquina)..."
if rclone --config "$RCLONE_CFG" lsl "$DRIVE_REMOTE:$DRIVE_FOLDER/$OUT" 2>/dev/null; then
  ok "confirmado no Drive"
else
  log "aviso: não consegui confirmar daqui (token/sandbox) — verifique no Drive"
fi

ok "CONCLUÍDO: Meu Drive/$DRIVE_FOLDER/$OUT"
