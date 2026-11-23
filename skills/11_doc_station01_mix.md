# Skill 11 — Station 01: Edit & Documentary Pack (Zero-Token)

Use esta skill sempre que o usuário pedir um vídeo documental, investigativo, histórico ou jornalístico usando os estilos da Estação 01 (ou um mix deles).

## Regra de Ouro (Zero-Token em Produção)
- **NUNCA** escreva código de renderização do zero para um vídeo novo.
- Leia `config/doc_station01_presets.json` e ofereça ao usuário escolher **1 estilo individual** ou **1 dos 3 mixes prontos por Ato** (ou um mix customizado).
- Gere **apenas** o JSON enxuto do episódio (`data/<slug>_station01.json`) seguindo o schema `DocStation01Spec` e execute o motor determinístico:

```bash
python3 engine/doc_station01_engine.py \
  --spec data/<slug>_station01.json \
  --audio outputs/<slug>/narracao.wav \
  --output outputs/<slug>/final_station01.mp4
```

## Estilos Disponíveis (`style`)
1. `caption_news` — Legenda gigante por chunks, `{palavra}` em bloco amarelo `#FFC21A`, número rolando no hook, `source_tag`.
2. `visual_investigation` — Bancada 1920x1080 @ 30fps, cronômetro sincronizado, *Freeze -> Circle -> Magnify*, fact-check `fact_claim` vs `fact_verdict`.
3. `newsreel_1920s` — Película 1920s, holofotes, jornal girando. *(Dica: aplicar `build_1920s_radio_audio_filter()` na voz TTS).*
4. `constructivist_montage` — Pôster alto contraste + faixa diagonal vermelha + contador rítmico + `red_wipe`.
5. `broadcast_news_package` — Bug `LIVE`, lower-third limpa com código de local e card OTS de dados.
6. `live_countdown_split` — Split-screen de 2 câmeras com relógio regressivo (`countdown_from_sec`).
7. `sports_telestrator` — Freeze-frame tático com anel pulsante e seta animada (`focus_point` -> `target_point`).
8. `city_symphony` — Letterbox 2.39:1, carimbo de hora minimalista e respiro cinematográfico.

## Mixes Prontos (definidos em `config/doc_station01_presets.json`)
- `mix_investigacao_completa` (Netflix / NYT Style)
- `mix_viral_curto` (1–3 min / Shorts & Reels)
- `mix_documentario_historico` (Arquivo & Época)

## Exemplo Mínimo de JSON (`DocStation01Spec`)
```json
{
  "title": "O Caso da Ponte",
  "channel_bug": "FRIMERISE DOCS",
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "scenes": [
    {
      "style": "caption_news",
      "duration": 3.5,
      "highlight_number": 42,
      "number_suffix": " SEGUNDOS",
      "caption_chunks": ["Tudo mudou em {42 segundos}", "e o arquivo provou"],
      "source_tag": "ARQUIVO 1978",
      "media_path": "outputs/caso/foto_01.jpg"
    },
    {
      "style": "visual_investigation",
      "duration": 5.0,
      "headline": "CRUZAMENTO DE PROVAS",
      "location_code": "SETOR 4 · 1978-08-12",
      "source_tag": "LAUDO OFICIAL",
      "clock_start_sec": 42.0,
      "fact_claim": "Versão inicial citou erro humano.",
      "fact_verdict": "3 sensores registraram falha estrutural.",
      "transition_in": "flash",
      "media_path": "outputs/caso/foto_02.jpg"
    }
  ]
}
```
