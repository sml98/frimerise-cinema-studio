# AGENTS.md — FrimeRise Cinema & Mixed-Media Documentary Studio

Este arquivo é o manual operacional canônico para **qualquer agente** (OpenBot, Codex, Antigravity, Claude Code, Cursor) que clonar este repositório. Leia-o **antes** de propor mudanças ou produzir vídeos.

---

## 1. Regra #1 — Poupar Tokens de Agente SEM Perder Qualidade

**Separe construir a fábrica de operar a fábrica:**
- **Use tokens de agente APENAS** para evoluir código, corrigir bugs ou criar novos modos visuais/skills.
- **NUNCA** use múltiplos turnos de agente para orquestrar manualmente etapas de TTS, download de mídia, render de cenas, `xfade`, QC ou upload.
- **Para produzir, retomar, validar ou empacotar vídeos**, execute **1 único comando Python** via `batch_produce.py` (ou dispare via API local `app.py`). Todo o pipeline já roda 100% em Python determinístico mantendo o padrão máximo **Cinema v3.0.0**:

```bash
# Vídeo documental 16:9 completo (17 min, padrão v3.0.0, QC automático + Drive + limpeza SSD):
.venv/bin/python batch_produce.py \
  --topic "A Verdadeira História Oculta da Biblioteca de Alexandria" \
  --engine netflix_doc --aspect 16:9 --minutes 17 --lang pt_br \
  --thumb-3words "O INCÊNDIO OCULTO"

# Produção em lote (0 tokens de agente; lê fila_videos.json):
.venv/bin/python batch_produce.py --queue fila_videos.json

# Retomar job interrompido aproveitando checkpoints (doc_scene_*.mp4 e base_scenes.mp4):
.venv/bin/python batch_produce.py --resume-job <JOB_ID>

# Rodar apenas o QC broadcast (ffprobe + ebur128 LUFS/dBTP) sem gastar LLM:
.venv/bin/python batch_produce.py --qc-only outputs/<JOB_ID>
```

---

## 2. Regra #2 — Quality Lock Inegociável (NUNCA Degradar Qualidade)

A especificação canônica está em `config/high_retention_doc_engine_v3.json` (e benchmarks em `config/reference_benchmarks_edl_v3.json`). **Nenhum agente pode reduzir nenhum parâmetro abaixo para economizar tempo ou tokens:**

### Vídeo & Ritmo Visual (Mixed-Media 5 Categorias)
- **Resolução & FPS:** `1920x1080 @ 30fps` (16:9 YouTube Long-Form) ou `1080x1920 @ 30fps` (9:16 Vertical). Nunca reduzir resolução do master ou FPS.
- **Zero-Copy Skia C++ + QuickSync VAAPI (`iHD`):** manter superfícies BGRA zero-copy com `h264_vaapi` (`format=nv12,hwupload`) e fallback seguro `libx264`.
- **5 Categorias Visuais Obrigatórias** (referências: *Vox, Johnny Harris, MagnatesMedia, Fern, Elementar*):
  1. `2.5D_Parallax` (`u2netp` ONNX + DOF 3px + movimento contra-direcional FG `1.00->1.14` / BG `1.06->1.00` + 3D Depth Title no Shot 0 com >=88% sem oclusão);
  2. `2D_Infographic_Over_Realism` (`2d_schematic_over_realism`, `dark_map_route`, `sliding_timeline`);
  3. `Video_Over_Video_PiP` (`video_over_video_collage`, `newspaper_highlighter`, `red_string_board`);
  4. `Dark_3D_Reconstruction` (`fern_3d_reconstruction` em `#121417` com spotlight volumétrico);
  5. `Atmospheric_B_Roll` (`0.85x` slow-motion filtrado por Vision Gate; **proibido** fallback genérico de stock ou abrir cena em B-roll fraco).
- **Visual Cohesion Unifier Stack:** contraste `+12%`, saturação `-22%`, sombras `#0D1B2A`, highlights `#E0C097`, vinheta `0.35`, granulação 35mm `0.14`, poeira atmosférica `0.16`, barra de progresso 3px `#D9381E -> #EAB308`.
- **Tipografia & Legendas:** `Cinzel-Bold.ttf` + `CourierPrime-Bold.ttf`; modo `selective_emphasis` no 16:9 e `cinema_minimal` no 9:16; zero caixas `[]` (sempre passar por `_sanitize_glyphs`).

### Narrativa & Retenção (5 Atos + RetentionDoctor v3)
- **Estrutura Long-Form 16:9:** 25 cenas, 2250–2450 palavras (~15–18 min), cronologia estritamente progressiva, palavra-chave do tema na 1ª frase, rigor factual (*Super Histórico / H2 History / Mega Curioso*).
- **5 Atos com direção de voz:** `ACT_0_COLD_OPEN_HOOK` (148 WPM, cortes 2.2s) -> `ACT_1_WORLD_BUILDING` (138 WPM) -> `ACT_2_DEEP_MECHANICS` (142 WPM + Pattern Interrupts a cada `240s` com silêncio musical de `1.25s`) -> `ACT_3_CLIMAX_REVELATION` (146 WPM, cortes 2.7s) -> `ACT_4_ABRUPT_ENDING` (110 WPM, **ZERO CTA de YouTube**, corte abrupto para preto `0.50s` após a última sílaba).
- **Mídia Histórica Sem Anacronismos:** Prioridade 1 Wikimedia Commons (>=900px, Vision Critic Gate + deduplicação perceptual 64-bit dHash); Prioridade 2 Google Flow Pro com Era-Lock obrigatório + triagem Vision contra anacronismos; Prioridade 3 B-roll 0.85x com Vision Gate.

### Áudio Broadcast (-14 LUFS / <= -1.0 dBTP)
- **Voz:** Gemini Expressive TTS (`Charon` / `Orus` / `Fenrir`) com alinhamento Whisper por palavra, VAD com silêncio interno máximo `0.35s` e nivelamento por cena.
- **Trilha & Foley:** trilha evolutiva em 4 movimentos (`-23 dB` base, auto-ducking `-28 dB` sob voz, vocal pocket carve `700–2500 Hz -4.5 dB`) + foley tátil sincronizado no frame exato (`marker_highlight_stroke`, `vector_draw_tick`, `pip_card_slide`, `scene_cut_sub_pulse`, `pattern_interrupt_shutter`).
- **Master Bus:** `-14.0 LUFS` integrado, **True Peak `<= -1.0 dBTP`** (limiter ceiling `0.79`), `LRA >= 4.5 LU`.

### Entregáveis Obrigatórios por Projeto
- `master.mp4`, `script.json`, `edl_timeline.json`, `words.json`, `quality_report.json`, `qc_report.json`, `timeline.otio`, `cover_9x16.png`, 3 thumbnails A/B 1280x720 (`thumb_A_mystery.jpg`, `thumb_B_contrast.jpg`, `thumb_C_zoom.jpg`), `preview_540p.mp4` e opcionalmente 5 Shorts 9:16 (`shorts_cascade/`).

---

## 3. Regra #3 — Proteção de Disco & Backup Automático no Google Drive

Vídeos Full HD de 15–18 minutos consomem vários GB durante a renderização. Siga sempre:
1. **Guarda de SSD:** nunca iniciar um render long-form com menos de **10 GB livres** em `/`.
2. **Limpeza intermediária automática durante o render:** [engine/netflix_doc_studio.py](engine/netflix_doc_studio.py) já apaga `doc_scene_*.mp4` / `_xfade_batch_*.mp4` assim que `base_scenes.mp4` é validado, e apaga `base_scenes.mp4` assim que `master.mp4` é muxado e verificado.
3. **Checkpoint / Resume:** `resume=True` reaproveita `doc_narr_*_vad.wav`, `doc_narr_*_words.json`, `doc_master_audio.m4a`, `doc_scene_*.mp4` e `base_scenes.mp4` intactos — **nunca** delete `_work/` de um job em andamento antes de verificar `base_scenes.mp4` ou `master.mp4`.
4. **Auto-Upload + Auto-Prune (padrão ATIVO):**
   - `gdrive_auto_upload = "1"` e `gdrive_prune_local = "1"` em [engine/gdrive_sync.py](engine/gdrive_sync.py).
   - **Somente após confirmar 100% do upload no Google Drive (`FrimeRise/<Projeto>_<Data>_<ID>/`)**, o sistema remove localmente `_work/`, `master.mp4`, mutações ShadowHash, `capcut_project.zip` e `.mp4` pesados de `shorts_cascade/` e `dubbed/`, preservando `preview_540p.mp4` + thumbs + JSONs.
   - Para conectar o servidor local ao Google Drive (1 única vez por máquina): `./setup_gdrive.sh` (`rclone`).

---

## 4. Mapa de Arquivos do Projeto

| Caminho | Função |
|---|---|
| `batch_produce.py` | CLI autônomo zero-token de agente (vídeo único, fila JSON, resume, QC broadcast). |
| `app.py` | Servidor FastAPI local (`http://127.0.0.1:8000`), fila sequencial, recuperação automática de jobs e UI web. |
| `database.py` | Camada SQLite WAL (`data/frimerise.db` — ignorado pelo Git). |
| `engine/pipeline.py` | Orquestrador unificado dos 3 Master Engines (`netflix_doc`, `cinematic_broll`, `cartoon_2d`). |
| `engine/netflix_doc_studio.py` | Motor documental Cinema v3.0.0 (5 Atos, Skia C++ Zero-Copy, 11 modos visuais, xfade, EDL). |
| `engine/doc_media_engine.py` | Wikimedia Commons, Google Flow era-lock, Gemini Vision Critic, dHash dedup, recorte 2.5D `u2netp`. |
| `engine/pro_motion_graphics.py` | Motion graphics Skia C++ (Depth Title, mapas cartográficos, jornal, board forense, timeline, Fern 3D). |
| `engine/audio_dsp.py` | Masterização `-14 LUFS`, limiter `<= -1.0 dBTP`, auto-ducking, VAD, Whisper alignment. |
| `engine/gemini_tts.py` | Gemini Native Expressive TTS com direção de atuação por ato. |
| `engine/gdrive_sync.py` | Upload automático em pastas nomeadas (`rclone` / Google API / GVFS) + limpeza segura pós-verificação. |
| `engine/intel_vaapi.py` | Encoder Intel QuickSync `h264_vaapi` (`iHD`), `os.nice`, guarda térmica da CPU. |
| `agents/retention_doctor.py` | Auditor automático RetentionDoctor v3 (clichês, open loops, CTAs, final abrupto). |
| `config/high_retention_doc_engine_v3.json` | Contrato canônico de qualidade v3.0.0. |
| `skills/` | Prompts e diretrizes editoriais por estilo (`10_netflix_investigative_doc.md`, etc.). |
| `setup_gdrive.sh` / `start_frimerise.sh` | Conexão `rclone` ao Drive e inicialização do servidor local. |

---

## 5. Setup Após `git clone` & Segurança de Credenciais

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bootstrap_assets.py
./setup_gdrive.sh          # Conecta Google Drive (rclone) para auto-upload + auto-prune
./start_frimerise.sh       # Sobe painel web em http://127.0.0.1:8000
```

- **NUNCA commite** `data/frimerise.db`, `.env`, `data/gdrive_token.json`, `data/gdrive_credentials.json`, `data/profiles/` ou `outputs/`.
- Configure chaves de API (`GEMINI_API_KEY`, `PIXABAY_API_KEY`, `PEXELS_API_KEY`) exclusivamente pela aba **Setup** da UI local ou via `database.save_settings(...)` no banco local.
- Respeite sempre fila sequencial (1 render por vez) e `thermal_guard_wait` para manter RAM estável e CPU segura.
