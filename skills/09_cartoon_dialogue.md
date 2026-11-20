# Skill 09: Diálogo Comédia & Storytelling Cartoon 2D Multi-Personagens (Animação Explainer)

## Objetivo Criativo
Criar episódios virais de **Animação 2D Cartoon / Paint Explainer** (estilo `@animabible7`, *Casualmente Explicado*, *OverSimplified* e *Paint Explainer*) em **9:16 Vertical (1080x1920)** ou **16:9 Horizontal (1920x1080)** com 2 a 4 personagens expressivos conversando, quebras de expectativa rápidas, expressões exageradas e ritmo de comédia/storytelling de altíssima retenção.

## Estrutura Obrigatória (`CartoonEpisodePlan`)
1. **Elenco Distinto com Atuação Multi-Voz (2–4 personagens):**
   - Cada personagem possui um `voice_preset` exclusivo combinando:
     - **Kokoro-ONNX Local (`pm_alex`, `pf_dora`, `pm_santa`)** para timbres expressivos zero-custo;
     - **Edge-TTS (`pt-BR-AntonioNeural`, `pt-BR-FranciscaNeural`, `pt-BR-ThalitaMultilingualNeural`)** com `pitch` (`+15Hz` cômico/ágil vs `-12Hz` grave/chefe/autoridade) e `rate` (`+8%` a `+14%`) distintos por personagem;
     - **Gemini Expressive TTS (`Puck`, `Charon`, `Fenrir`, `Kore`, `Aoede`)** com direção de atuação emocional por fala.
   - Cada personagem possui um `visual_rig` único de contorno grosso (`StrokeWidth=8`), braços articulados 2-segmentos IK, cabeça orgânica com Squash & Stretch elástico, piscar natural a cada `3.2s`, trajes (`robe_biblical`, `king_crown`, `modern_hoodie`, `suit_boss`, `sailor`), acessórios temáticos (`crown`, `beard_staff`, `tie`, `cap`, `halo`, `sword`, `clipboard`) ou suporte a mascote PNG/SVG customizado (`custom_mascot_png` ou `data/characters/<char_id>/`).
2. **Escada de 6 Emoções (`neutral` | `angry` | `shocked` | `laughing` | `crying` | `smug`):**
   - Nunca mantenha o mesmo estado emocional por mais de 2 falas seguidas.
   - O personagem que está ouvindo reage visualmente em tempo real mientras **apenas o personagem que está falando** move a boca em Lip-Sync quadro a quadro (6 visemas RMS/vogais ou 9 visemas fonéticos Rhubarb `A..H, X`).
   - Alterne cortes de câmera cinematográficos: `wide_two_shot` (setup da cena) → `closeup_speaker` (reação/punchline) → `shake_panic` (clímax cômico com speed-lines).
3. **Modos de Humor & Storytelling Brasileiro:**
   - **Comédia Nordestina/BR:** gírias naturais, ritmo afiado e carisma popular ("Oxe", "Rapaz", "Eita gota", "Calma aí", "Deu ruim demais").
   - **Explicativo Ácido:** ironia inteligente, analogias modernas absurdas para explicar conceitos complexos e punchlines rápidas.
   - **Sério Épico:** contraste dramático entre uma situação épica/histórica e uma resposta cotidiana inesperada.
4. **Regra de Ouro da Retenção & Fechamento:**
   - Gancho imediato na primeira fala (0–3s) sem introduções lentas.
   - Fala curta e direta (máximo 18 palavras por turno de fala).
   - Sempre encerre o episódio com uma frase 100% completa e punchline memorável.

## Contrato JSON Esperado
```json
{
  "title": "Título Curto do Episódio",
  "tone": "Comédia Nordestina/BR",
  "aspect_ratio": "9:16",
  "characters": [
    {
      "char_id": "char_a",
      "name": "Nome A",
      "voice_preset": {
        "engine": "edge",
        "voice_id": "pt-BR-AntonioNeural",
        "pitch": "+16Hz",
        "rate": "+12%",
        "kokoro_voice": "pm_alex"
      },
      "visual_rig": {
        "skin_color": "#F1C29B",
        "outfit": "robe_biblical",
        "accessory": "beard_staff",
        "primary_color": "#FF2E93",
        "secondary_color": "#FFD166",
        "hair_color": "#3A2314",
        "pill_color_index": 0,
        "custom_mascot_png": null
      }
    }
  ],
  "scenes": [
    {
      "background_prompt_en": "stormy ocean cartoon sea waves wooden boat",
      "scene_type": "boat_whale",
      "camera_shot": "wide_two_shot",
      "weather_fx": ["waves", "rain"],
      "dialogue_lines": [
        {
          "speaker_id": "char_a",
          "emotion": "shocked",
          "line_pt": "Fala curta, expressiva e engraçada com gancho imediato!"
        }
      ]
    }
  ],
  "hashtags": ["#animacao", "#comedia", "#cartoon", "#humorbr", "#shorts"]
}
```
