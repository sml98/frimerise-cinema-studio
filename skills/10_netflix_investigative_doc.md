# Skill 10: Documentário Investigativo Cinema v3.0.0 (Mixed-Media High-Retention Engine)

## Objetivo Criativo & Quality Lock v3.0.0
Construir roteiros e planos visuais de **Documentário Investigativo Cinematográfico de Alto RPM** seguindo o contrato canônico `config/high_retention_doc_engine_v3.json` (`schema_version: 3.0.0`):
- **16:9 YouTube Long-Form (`1920x1080 @ 30fps`)**: 15 a 18 minutos (ideal **17.0 min**, 25 cenas, 2.250–2.450 palavras, 90–98 palavras/cena), escalável para mini-docs (1–8 min) e **9:16 Vertical Doc (`1080x1920 @ 30fps`)**.
- **Idiomas nativos suportados:** Português-BR (`pt_br`), Inglês-US (`en_us`) e Espanhol (`es`).
- **Referências editoriais:** *Super Histórico, H2 History, Mega Curioso* (rigor factual BBC/Netflix Standards & Practices, cronologia estritamente progressiva, palavra-chave do tema na 1ª frase).
- **Referências visuais:** *Vox, Johnny Harris, MagnatesMedia, Fern, Elementar*.
- **Identidade de canal:** Crie `channel_name` coerente com o `mood` do tema (`dark_horror`, `epic_history`, `investigative_crime`, `corporate_thriller`) — use `"Dossiê Capital"` / `"Vault Files"` apenas quando `mood == "corporate_thriller"`.

## Arquitetura Dramática em 5 Atos (Cold Open -> Final Abrupto Zero-CTA)
1. **`ACT_0_COLD_OPEN_HOOK` (Cenas 0–1 | 0–75s | cortes ~2.2s | ~148 WPM):**
   - Nomeie explicitamente a palavra-chave central do tema já na **1ª frase** e estabeleça o paradoxo histórico/investigativo imediatamente.
   - Proibido começar com *"Olá pessoal"*, *"Em um mundo onde"* ou *"Vamos mergulhar"*.
   - Feche a Cena 1 com uma pergunta investigativa direta e concisa (`<= 16 palavras`) com entonação interrogativa ascendente genuína.
2. **`ACT_1_WORLD_BUILDING` (Cenas 2–6 | cortes ~4.0s | ~138 WPM):**
   - Construa contexto geográfico, datas primárias e fontes verificáveis avançando estritamente no tempo (nunca salte para trás na cronologia).
3. **`ACT_2_DEEP_MECHANICS` (Cenas 7–15 | cortes ~3.5s | ~142 WPM):**
   - Detalhe mecanismos ocultos, decretos, documentos e conexões causais; aplique **Pattern Interrupts** a cada `240s` (`240s, 480s, 720s`) com silêncio musical suave de `1.25s` sobre `room_tone_bed.wav` e transição seca (`pattern_interrupt_shutter.wav`).
4. **`ACT_3_CLIMAX_REVELATION` (Cenas 16–21 | cortes ~2.7s | ~146 WPM):**
   - Acelere a cadência visual à medida que as forças históricas convergem para a virada decisiva.
5. **`ACT_4_ABRUPT_ENDING` (Cenas 22–24 | cortes ~4.5s | ~110–130 WPM):**
   - Síntese forense conectando o passado ao presente. **ZERO CTA de YouTube** (proibido pedir like, inscrição, sininho ou despedida). Corte abrupto para tela preta exatos `0.50s` após a última sílaba falada.

## Matriz Visual Mixed-Media (5 Categorias Obrigatórias • Skia C++ Zero-Copy + VAAPI)
1. **`2.5D_Parallax`** (`parallax_25d_photo`, `cinema_multishot`): recorte `u2netp` ONNX com desfoque DOF `3px`, movimento contra-direcional (FG `1.00->1.14` / BG `1.06->1.00`) e **3D Depth Title** exclusivo no Shot 0 (`>= 92%` livre de oclusão).
2. **`2D_Infographic_Over_Realism`** (`2d_schematic_over_realism`, `dark_map_route`, `sliding_timeline`): esquemas táticos Vox/Johnny Harris com cartões locais da cena, mapas cartográficos com origem != destino e timelines sincronizadas com placas históricas da época.
3. **`Video_Over_Video_PiP`** (`video_over_video_collage`, `newspaper_highlighter`, `red_string_board`): colagem flutuante PiP, recorte de jornal de época com marca-texto `#FFD700` (`kMultiply`) e quadro forense de fios vermelhos com placas da era correspondente.
4. **`Dark_3D_Reconstruction`** (`fern_3d_reconstruction`): reconstrução espacial em `#121417` com grade 3D, holofote volumétrico e silhueta/monólito arquivístico.
5. **`Atmospheric_B_Roll`**: filmagens reais a `0.85x` aprovadas pelo Vision Gate estrito; nunca abrir cena em B-roll genérico ou anacrônico.

## Coesão Visual, Tipografia & Áudio Broadcast
- **Visual Cohesion Unifier Stack (pré-UI em Skia C++):** contraste `+12%`, saturação `-22%`, sombras `#0D1B2A`, highlights `#E0C097`, vinheta `0.35`, granulação 35mm `0.14`, poeira atmosférica `0.16`, acentos `#EAB308` / `#D9381E` / `#F8FAFC` e barra de progresso 3px `#D9381E -> #EAB308`.
- **Tipografia & Legendas:** `Cinzel-Bold.ttf` (títulos/capítulos) + `CourierPrime-Bold.ttf` (HUD forense/legendas); modo `selective_emphasis` no 16:9 e `cinema_minimal` no 9:16; sem caixas de glifo (`[]`) nem colisão com Lower Thirds.
- **Voz & Master Bus:** Gemini Expressive TTS (`Charon` / `Orus` / `Fenrir`) travado em **1 único modelo** por documentário inteiro (nunca misturar modelos/engines no meio do vídeo) + Gate acústico de consistência de locutor; Master `-14.0 LUFS`, True Peak `<= -1.0 dBTP`, `LRA >= 4.5 LU`.
- **Mídia sem Anacronismos:** Google Flow Pro com Era-Lock obrigatório + Wikimedia Commons com Gemini Vision Critic estrito (`strict_vision=True`); cada cena fornece `shot_prompts_en` cronológicos sincronizados às frases da narração.

## Regra de Ouro de Retenção (RetentionDoctor v3)
- Cada cena entrega dados concretos (ano, local, instituição, documento ou consequência histórica real) sem clichês robóticos de IA.
- Distribua Open Loops ao longo de todo o documentário (nunca concentre tudo numa única cena) e responda cada pergunta na cena seguinte.
- Alterne as 5 categorias visuais para que cenas consecutivas nunca repitam o mesmo layout.

## Contrato JSON Esperado (`NetflixDocPlan` v3.0.0)
```json
{
  "schema_version": "3.0.0",
  "pipeline_name": "Mixed_Media_High_Retention_Documentary_Engine",
  "title": "Título Editorial Investigativo",
  "subtitle": "Arquivo Histórico • Recorte Cronológico",
  "channel_name": "Nome do Canal Coerente com o Mood",
  "mood": "dark_horror | epic_history | investigative_crime | corporate_thriller",
  "lang": "pt_br",
  "aspect_ratio": "16:9",
  "target_minutes": 17.0,
  "voice_id": "Charon",
  "caption_style": "selective_emphasis",
  "thumbnail_hook": "TRÊS PALAVRAS FORTES",
  "pattern_interrupt_times": [240.0, 480.0, 720.0],
  "scenes": [
    {
      "scene_id": "doc_sc_01",
      "act_id": "ACT_0_COLD_OPEN_HOOK",
      "act_label": "COLD OPEN",
      "chapter_card": null,
      "chapter_subtitle": "TÍTULO TEMÁTICO DA CENA",
      "visual_mode": "parallax_25d_photo",
      "visual_category": "2.5D_Parallax",
      "cut_cadence_s": 2.2,
      "pattern_interrupt": false,
      "narration": "90-98 palavras faladas naturais (15-18 min long-form), nomeando o tema já na 1ª frase, sem travessões nem clichês de IA.",
      "lower_third_title": "LOCALIZAÇÃO • DATA EXATA",
      "lower_third_subtitle": "CONTEXTO ARQUIVÍSTICO • FONTE PRIMÁRIA",
      "highlight_color": "#EAB308",
      "evidence_headline": "MANCHETE DOCUMENTAL CURTA DA CENA",
      "evidence_quote": "Fato histórico ou trecho documental verificável específico desta cena.",
      "map_origin": "ORIGEM HISTÓRICA",
      "map_destination": "DESTINO HISTÓRICO",
      "map_metric": "MÉTRICA OU MARCO HISTÓRICO",
      "timeline_points": [
        {"date": "ANO 1", "label": "Marco Verificável 1", "value": "IMPACTO 1"},
        {"date": "ANO 2", "label": "Marco Verificável 2", "value": "IMPACTO 2"},
        {"date": "ANO 3", "label": "Marco Verificável 3", "value": "IMPACTO 3"}
      ],
      "board_nodes": [
        {"id": "n1", "title": "ENTIDADE 1", "role": "Papel Histórico", "badge": "ARQUIVO #01"},
        {"id": "n2", "title": "ENTIDADE 2", "role": "Mecanismo", "badge": "PROVA"},
        {"id": "n3", "title": "ENTIDADE 3", "role": "Decreto / Evento", "badge": "VIRADA"},
        {"id": "n4", "title": "ENTIDADE 4", "role": "Consequência", "badge": "LEGADO"}
      ],
      "broll_query_en": "concrete atmospheric historical stock video query",
      "pip_broll_query_en": "different concrete atmospheric stock video query",
      "photo_query_en": "specific historical engraving or artwork subject",
      "extra_photo_queries_en": ["specific subject 1", "specific subject 2", "specific subject 3"],
      "bespoke_image_prompt_en": "dramatic 35mm dark cinema historical still matching beat 1, period authentic, chiaroscuro lighting, no text",
      "shot_prompts_en": [
        "chronological beat 1 prompt, 35mm cinema, period authentic, no text",
        "chronological beat 2 prompt, close-up detail, period authentic, no text",
        "chronological beat 3 prompt, wide architectural angle, period authentic, no text",
        "chronological beat 4 prompt, atmospheric candlelit frame, period authentic, no text"
      ]
    }
  ]
}
```
