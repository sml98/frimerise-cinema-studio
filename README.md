# FrimeRise Cinema & Mixed-Media Documentary Studio (v3.0.0)

Estúdio local de produção automatizada de documentários cinematográficos, vídeos virais híbridos e animações 2D — rodando **100% em Python + Skia C++ Zero-Copy + Intel QuickSync VAAPI + FFmpeg**, com **backup automático no Google Drive e limpeza inteligente do SSD**.

> **Agentes (OpenBot, Codex, Antigravity, Claude Code):** leia primeiro [`AGENTS.md`](./AGENTS.md) para entender toda a arquitetura, o **Quality Lock v3.0.0** e o fluxo **zero-token de agente** via `batch_produce.py`.

---

## Principais Recursos

- **3 Motores Master:**
  - `netflix_doc` (**Mixed-Media High-Retention Documentary Engine v3.0.0**): 16:9 Full HD (15–18 min, 25 cenas, 5 Atos) e 9:16 Vertical, combinando 5 categorias visuais (*2.5D Parallax `u2netp`, Infográficos 2D sobre Realismo, Video-over-Video PiP/Jornal/String Board, Reconstrução Dark 3D estilo Fern e B-Roll 0.85x com Vision Gate*).
  - `cinematic_broll`: Vídeos dinâmicos virais com mixer híbrido de bibliotecas visuais, legendas cinéticas e motion cards Skia.
  - `cartoon_2d`: Animação 2D multi-personagens @ 60fps com lip-sync Rhubarb 9-visemas.
- **Qualidade Broadcast Travada (`config/high_retention_doc_engine_v3.json`):**
  - Gemini Expressive TTS + alinhamento Whisper por palavra + masterização `-14.0 LUFS` com teto estrito `<= -1.0 dBTP` + auto-ducking e foley tátil sincronizado no frame.
  - Wikimedia Commons + Google Flow Pro com Era-Lock histórico, triagem Gemini Vision contra anacronismos e deduplicação perceptual dHash 64-bit.
  - **RetentionDoctor v3** + Pattern Interrupts a cada 240s + final abrupto de 0.50s sem CTA.
- **Produção Zero-Token de Agente (`batch_produce.py`):**
  - Dispara vídeos únicos ou filas inteiras (`fila_videos.json`) via Python puro com guarda de espaço em disco, guarda térmica, checkpoint/resume automático (`doc_scene_*.mp4` e `base_scenes.mp4`) e QC automático (`ffprobe` + `ebur128`).
- **Armazenamento Infinito (Google Drive + Auto-Prune):**
  - Envia cada projeto finalizado para `Google Drive -> FrimeRise/<Projeto>_<Data>_<ID>/` e, somente após confirmar o upload, remove automaticamente `_work/`, `master.mp4`, mutações ShadowHash, `capcut_project.zip` e `.mp4` pesados de `shorts_cascade/` e `dubbed/`, preservando a prévia leve `540p`, thumbnails e metadados.

---

## Instalação Rápida (após `git clone`)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bootstrap_assets.py
```

### Conectar Google Drive (1 comando, 1 vez por máquina)
```bash
./setup_gdrive.sh
```

---

## Como Usar

### 1) Modo Automático Zero-Token (CLI Python — Recomendado para Produção)
```bash
# Produzir um documentário 16:9 completo (17 min, padrão v3.0.0)
.venv/bin/python batch_produce.py \
  --topic "A Verdadeira História Oculta da Biblioteca de Alexandria" \
  --engine netflix_doc --aspect 16:9 --minutes 17 --lang pt_br \
  --thumb-3words "O INCÊNDIO OCULTO"

# Produzir uma fila inteira de vídeos (copie fila_videos.example.json para fila_videos.json)
cp fila_videos.example.json fila_videos.json
.venv/bin/python batch_produce.py --queue fila_videos.json

# Retomar um job interrompido reaproveitando checkpoints
.venv/bin/python batch_produce.py --resume-job <JOB_ID>

# Auditar qualidade técnica (vídeo/áudio/LUFS/True Peak) sem gastar tokens
.venv/bin/python batch_produce.py --qc-only outputs/<JOB_ID>
```

### 2) Painel Web Local (`http://127.0.0.1:8000`)
```bash
./start_frimerise.sh --keep-awake
```

Configure suas chaves de API na aba **⚙️ Setup** do painel (armazenadas apenas localmente em `data/frimerise.db`, nunca enviadas ao Git).
