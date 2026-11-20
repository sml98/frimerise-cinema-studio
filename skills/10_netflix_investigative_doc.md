# Skill 10: Documentário Investigativo Cinema (Estilo Netflix / MagnatesMedia / Vox / ColdFusion)

## Objetivo Criativo
Construir roteiros e planos visuais de **Documentário Investigativo Cinematográfico de Alto RPM** em **16:9 Widescreen (1920x1080)** (escalável de 25s demonstrativos até 3–15 minutos para YouTube Mid-Roll Ads) e **9:16 Vertical Doc (1080x1920)** nos idiomas **Português-BR (`pt_br` — Canal "Dossiê Capital")** e **Inglês-US (`en_us` — Canal "Vault Files")**.

## Arquitetura Dramática em Atos (Cold Open + Capítulos + Retenção Mid-Roll)
1. **Cold Open Magnético (0–15s):**
   - Comece direto no momento de maior tensão financeira, fraude, anomalia bilionária ou paradoxo histórico (ex: *"Em 24 de fevereiro de 1995, um único operador em Singapura escondeu 1,4 bilhão de dólares debaixo do tapete do banco mais antigo do Império Britânico..."*).
   - Proibido começar com *"Olá pessoal"* ou introduções genéricas.
2. **Cartões de Capítulo Cinematográficos (`C A P Í T U L O   I`, `C A P Í T U L O   I I`, `C A P Í T U L O   I I I`):**
   - Tipografia espaçada de cinema (`wide letter-spacing`), fundo escuro `#0B0713` com acento Dourado (`#FFD166`) ou Rosa (`#FF2E93`), acompanhado de impacto sonoro grave `assets/sfx/sub_boom.wav`.
3. **Lower Thirds Investigativos & Color Grading `02_dark_wealth.cube` + Grão 35mm:**
   - Cada cena exibe um Lower Third editorial limpo com Localização, Data exata ou Classificação Forense (ex: `SINGAPURA • CONTA SECRETA #88888`, `AUDITORIA FORENSE • US$ 2.1 BILHÕES`).
4. **Os 5 Modos Visuais Investigativos Renderizados em Skia C++ (30fps):**
   - `parallax_25d_photo`: Fotografia histórica/arquivística em camadas com paralaxe 2.5D, partículas de poeira de projetor, vinheta dramática e moldura forense.
   - `newspaper_highlighter`: Recorte de jornal financeiro ou documento confidencial com animação de marca-texto (`Multiply-blend highlighter sweep`) em Dourado (`#FFD166`) ou Rosa (`#FF2E93`) grifando a frase-chave da prova.
   - `dark_map_route`: Mapa tático investigativo escuro (mundo/cidade) com grade de coordenadas, rota tracejada animada e pino de destino pulsante com brilho néon.
   - `sliding_timeline`: Linha do tempo deslizante horizontal/vertical conectando datas críticas, cifras bilionárias e eventos da escalada do caso.
   - `red_string_board`: Quadro investigativo escuro de evidências conectando suspeitos, empresas de fachada e contas ocultas com fios vermelhos/rosa brilhantes (`#FF2E93`).

## Regra de Ouro de Retenção (Doctor Audit)
- Cada cena deve conter pelo menos um **dado concreto** (ano, cifra em dólares/reais, nome de instituição, código de conta ou localização geográfica) e um **conector de tensão** (*"mas o que ninguém sabia"*, *"só que havia um detalhe oculto"*, *"foi aí que tudo mudou"*).
- Alterne os 5 modos visuais (`parallax_25d_photo`, `newspaper_highlighter`, `dark_map_route`, `sliding_timeline`, `red_string_board`) para que duas cenas seguidas nunca repitam exatamente o mesmo layout visual.

## Contrato JSON Esperado (`NetflixDocPlan`)
```json
{
  "title": "O Operador que Quebrou o Banco da Rainha",
  "subtitle": "Dossiê Investigativo • Caso Barings Bank",
  "channel_name": "Dossiê Capital",
  "lang": "pt_br",
  "aspect_ratio": "16:9",
  "target_minutes": 0.5,
  "lut_file": "02_dark_wealth.cube",
  "voice_id": "pt-BR-AntonioNeural",
  "thumbnail_hook": "ESCONDEU $1.4 BILHÃO",
  "scenes": [
    {
      "scene_id": "sc_01",
      "act_label": "COLD OPEN",
      "chapter_card": null,
      "chapter_subtitle": null,
      "visual_mode": "parallax_25d_photo",
      "narration": "Em fevereiro de 1995, um único erro escondido numa conta secreta derrubou um império bancário de 233 anos.",
      "lower_third_title": "LONDRES & SINGAPURA • 1995",
      "lower_third_subtitle": "CASO BARINGS BANK • ARQUIVO #88888",
      "highlight_color": "#FFD166",
      "evidence_headline": "BARINGS COLLAPSES AFTER $1.4B SECRET LOSS",
      "evidence_quote": "Account 88888 concealed unauthorized futures trades for 32 months.",
      "map_origin": "LONDRES",
      "map_destination": "SINGAPURA",
      "map_metric": "US$ 1.4 BILHÃO OCULTO",
      "timeline_points": [
        {"date": "1992", "label": "Conta #88888 Criada", "value": "-US$ 2M"},
        {"date": "1994", "label": "Apostas Dobradas", "value": "-US$ 208M"},
        {"date": "1995", "label": "Colapso em Tóquio", "value": "-US$ 1.4B"}
      ],
      "board_nodes": [
        {"id": "n1", "title": "NICK LEESON", "role": "Operador Chefe SIMEX", "badge": "SUSPEITO #1"},
        {"id": "n2", "title": "CONTA #88888", "role": "Esconderijo de Perdas", "badge": "CAIXA PRETA"},
        {"id": "n3", "title": "BARINGS BANK", "role": "Fundado em 1762", "badge": "FALÊNCIA"},
        {"id": "n4", "title": "NIKKEI 225", "role": "Contratos Futuros", "badge": "-US$ 1.4B"}
      ],
      "image_prompt_en": "cinematic dark moody 1990s stock exchange trading floor archival photo"
    }
  ]
}
```
