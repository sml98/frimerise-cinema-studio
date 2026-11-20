"""FrimeRise Netflix / MagnatesMedia Cinema Investigative Documentary Studio (Skia C++ + QuickSync iHD).
Features:
  - Supports 16:9 Widescreen (1920x1080, scalable from 25s demos up to 3-15 min high-RPM mid-roll documentaries)
    and 9:16 Vertical Doc (1080x1920).
  - Scene-by-scene disk rendering with os.nice(10) and thermal_guard_wait so RAM stays flat and Core i5 stays cool.
  - Dramatic Act Structure: Cold Open + Wide Letter-Spaced Chapter Cards ('C A P Í T U L O   I', 'C A P Í T U L O   I I')
    with assets/sfx/sub_boom.wav impact + sleek editorial Lower Thirds + LUT assets/luts/02_dark_wealth.cube + 35mm film grain.
  - 5 Investigative C++ Skia Visual Modes @ 30fps:
      1) parallax_25d_photo: Historical/archival photo with 2.5D depth parallax, dust motes & anamorphic vignette
      2) newspaper_highlighter: Financial newspaper/dossier clipping with animated Multiply-blend highlighter sweep (#FFD166 / #FF2E93)
      3) dark_map_route: Dark tactical world/city map with animated dashed Bézier route & glowing destination pin
      4) sliding_timeline: Horizontal/vertical camera-tracked sliding timeline of dates & financial figures
      5) red_string_board: Investigative obsidian/cork board connecting suspects/companies/evidence nodes with glowing #FF2E93 strings
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import urllib.parse
import wave
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import edge_tts
import httpx
from pydantic import BaseModel, Field
import skia

from agents.llm_router import _extract_json, get_settings, record_token_usage
from agents.retention_doctor import audit_viral_script_dict
from engine.audio_dsp import (
    _estimate_word_timestamps,
    _get_wav_duration,
    _synthesize_espeak_fallback,
    master_broadcast_audio,
    synthesize_kokoro_blended,
    trim_silence_vad,
)
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    FORBIDDEN_DEBUG_RE,
    _ease_out_cubic,
    _load_verified_typeface,
    _wrap_text_to_width,
    group_words_into_chunks,
    hex_to_skia,
)

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
SKILLS_DIR = BASE_DIR / "skills"
DOC_BG_CACHE = BASE_DIR / "data" / "doc_bgs"
DOC_BG_CACHE.mkdir(parents=True, exist_ok=True)

VisualModeType = Literal[
    "parallax_25d_photo",
    "newspaper_highlighter",
    "dark_map_route",
    "sliding_timeline",
    "red_string_board",
]

VISUAL_MODES: Tuple[VisualModeType, ...] = (
    "parallax_25d_photo",
    "newspaper_highlighter",
    "dark_map_route",
    "sliding_timeline",
    "red_string_board",
)

ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")


def _spaced_chapter_label(roman: str, lang: str = "pt_br") -> str:
    """Return wide letter-spaced cinema chapter title, always including C A P Í T U L O."""
    r_spaced = " ".join(list(roman.strip()))
    if lang == "en_us":
        return f"C A P Í T U L O   {r_spaced}   •   C H A P T E R   {r_spaced}"
    return f"C A P Í T U L O   {r_spaced}"


def _clean_doc_text(text: str) -> str:
    cleaned = FORBIDDEN_DEBUG_RE.sub("", str(text or "")).strip()
    return " ".join(cleaned.split())


# ---------------------------------------------------------------------------
# 1. Pydantic Models & JSON Contract for Netflix / MagnatesMedia Doc Studio
# ---------------------------------------------------------------------------
class TimelinePoint(BaseModel):
    date: str
    label: str
    value: str


class BoardNode(BaseModel):
    id: str
    title: str
    role: str
    badge: str


class NetflixDocScene(BaseModel):
    scene_id: str
    act_label: str = "ACT I"
    chapter_card: Optional[str] = None
    chapter_subtitle: Optional[str] = None
    visual_mode: VisualModeType = "parallax_25d_photo"
    narration: str
    lower_third_title: str
    lower_third_subtitle: str
    highlight_color: str = "#FFD166"
    evidence_headline: str = "CLASSIFIED FINANCIAL AUDIT REPORT"
    evidence_quote: str = "Internal ledgers revealed concealed multi-million transfers across offshore accounts."
    map_origin: str = "LONDON"
    map_destination: str = "SINGAPORE"
    map_metric: str = "$1.4 BILLION EXPOSURE"
    timeline_points: List[TimelinePoint] = Field(default_factory=list)
    board_nodes: List[BoardNode] = Field(default_factory=list)
    image_prompt_en: str = "cinematic dark archival investigative financial trading floor photograph"


class NetflixDocPlan(BaseModel):
    title: str
    subtitle: str
    channel_name: str = "Dossiê Capital"
    lang: str = "pt_br"
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    target_minutes: float = 0.5
    lut_file: str = "02_dark_wealth.cube"
    voice_id: str = "pt-BR-AntonioNeural"
    thumbnail_hook: str = "ESCONDEU $1.4 BILHÃO"
    scenes: List[NetflixDocScene]
    hashtags: List[str] = Field(default_factory=lambda: ["#documentario", "#investigacao", "#financas", "#cinema"])


# ---------------------------------------------------------------------------
# 2. Curated Investigative Dossiers (10 High-RPM Twin-Channel Episodes + Custom)
# ---------------------------------------------------------------------------
_CURATED_DOSSIERS: List[Dict[str, Any]] = [
    {
        "keywords": ("leeson", "barings", "88888", "rainha", "singapura"),
        "title_pt": "Nick Leeson: O Operador que Quebrou o Banco da Rainha",
        "title_en": "Nick Leeson: The Rogue Trader Who Collapsed Barings Bank",
        "sub_pt": "Dossiê Forense • Conta Secreta #88888",
        "sub_en": "Forensic File • Secret Error Account #88888",
        "hook_pt": "ESCONDEU $1.4 BILHÃO",
        "hook_en": "HID $1.4 BILLION",
        "origin": "LONDRES",
        "dest": "SINGAPURA",
        "metric_pt": "US$ 1.4 BILHÃO OCULTO",
        "metric_en": "$1.4 BILLION CONCEALED",
        "headline": "BARINGS BANK COLLAPSES OVERNIGHT AFTER $1.4B SECRET LOSS",
        "quote_pt": "A conta de erro 88888 escondeu prejuízos bilionários em contratos futuros do Nikkei por 32 meses sem auditoria.",
        "quote_en": "Error Account 88888 concealed unauthorized Nikkei futures losses for 32 months while London sent more capital.",
        "timeline": [
            {"date": "1992", "label": "Conta #88888 Aberta", "value": "-US$ 2M"},
            {"date": "1993", "label": "Especulação SIMEX", "value": "-US$ 23M"},
            {"date": "1994", "label": "Auditoria Enganada", "value": "-US$ 208M"},
            {"date": "1995", "label": "Terremoto de Kobe", "value": "-US$ 1.4B"},
        ],
        "nodes": [
            {"id": "n1", "title": "NICK LEESON", "role": "Chefe de Operações SIMEX", "badge": "OPERADOR"},
            {"id": "n2", "title": "CONTA #88888", "role": "Arquivo Oculto de Erros", "badge": "CAIXA PRETA"},
            {"id": "n3", "title": "BARINGS (1762)", "role": "233 Anos de História", "badge": "VENDIDO POR £1"},
            {"id": "n4", "title": "NIKKEI 225", "role": "Aposta Dobrada em Tóquio", "badge": "-US$ 1.4 BILHÃO"},
        ],
        "narr_pt": [
            "Em fevereiro de 1995, um único operador de vinte e oito anos em Singapura derrubou o banco mais antigo da coroa britânica — só que ninguém em Londres desconfiava do número 88888.",
            "Para esconder um pequeno erro de uma funcionária, Nick Leeson abriu a conta secreta cinco vezes oito, mas o que começou com dois milhões virou uma bola de neve fora de controle.",
            "Enquanto a matriz em Londres acreditava que ele gerava lucros recordes, centenas de milhões de dólares cruzavam o planeta para cobrir margens ocultas na bolsa asiática.",
            "Quando o terremoto de Kobe derrubou o índice Nikkei em janeiro de 1995, Leeson dobrou a aposta final e o rombo explodiu para um vírgula quatro bilhão de dólares.",
            "Em quarenta e oito horas, um império financeiro de duzentos e trinta e três anos foi vendido por exatamente uma libra esterlina.",
        ],
        "narr_en": [
            "In February 1995, a single twenty-eight-year-old trader in Singapore brought down Britain's oldest merchant bank — yet nobody in London questioned Account 88888.",
            "To hide a tiny clerical mistake on the trading floor, Nick Leeson opened secret error account five-eights, but a two-million-dollar loss quickly spiraled out of control.",
            "While executives in London praised him as a miracle profit machine, hundreds of millions of dollars were wired across the globe to feed hidden margin calls.",
            "When the Kobe earthquake sent the Nikkei crashing in January 1995, Leeson doubled down one last time and the secret hole exploded to one point four billion dollars.",
            "Within forty-eight hours, a two-hundred-and-thirty-three-year financial empire collapsed and was sold for a single British pound.",
        ],
    },
    {
        "keywords": ("luxottica", "óculos", "oculos", "monopólio", "monopolio", "ray-ban", "oakley"),
        "title_pt": "A Ilusão da Escolha: O Império Secreto dos Óculos",
        "title_en": "The Illusion of Choice: Inside the Eyewear Monopoly",
        "sub_pt": "Dossiê Antitruste • Margem de 2.000%",
        "sub_en": "Antitrust File • 2,000% Markup Architecture",
        "hook_pt": "TUDO É DELES",
        "hook_en": "THEY OWN ALL",
        "origin": "MILÃO",
        "dest": "NOVA YORK",
        "metric_pt": "+2.000% DE MARGEM",
        "metric_en": "+2,000% RETAIL MARKUP",
        "headline": "ONE CONGLOMERATE CONTROLS 80% OF GLOBAL EYEWEAR BRANDS",
        "quote_pt": "Quando a Oakley tentou desafiar os preços do grupo, foi retirada das vitrines até suas ações caírem e ser comprada pelo próprio rival.",
        "quote_en": "When Oakley resisted pricing terms, its frames vanished from retail chains until its stock tumbled into a buyout.",
        "timeline": [
            {"date": "1961", "label": "Oficina em Agordo", "value": "US$ 100K"},
            {"date": "1999", "label": "Compra da Ray-Ban", "value": "US$ 640M"},
            {"date": "2007", "label": "Aquisição da Oakley", "value": "US$ 2.1B"},
            {"date": "2018", "label": "Fusão EssilorLuxottica", "value": "US$ 57B"},
        ],
        "nodes": [
            {"id": "n1", "title": "ESSILORLUXOTTICA", "role": "Holding Dominante", "badge": "80% DO MERCADO"},
            {"id": "n2", "title": "RAY-BAN & OAKLEY", "role": "Marcas 'Rivais' Internas", "badge": "MESMO DONO"},
            {"id": "n3", "title": "SUNGLASS HUT", "role": "Rede Global de Varejo", "badge": "CONTROLE DE PREÇO"},
            {"id": "n4", "title": "CUSTO REAL US$ 12", "role": "Vendido por US$ 300+", "badge": "MARGEM 2.000%"},
        ],
        "narr_pt": [
            "Você entra em um shopping, compara dez marcas diferentes de óculos de sol achando que está pesquisando preço — só que quase todas pertencem exatamente à mesma fábrica.",
            "Durante décadas, uma única gigante italiana comprou silenciosamente as fábricas de armações, as maiores marcas de luxo e até as redes de óticas onde você compra.",
            "Quando a Oakley tentou vender mais barato em 2001, ela foi banida das maiores vitrines dos Estados Unidos até perder valor de mercado e ser comprada pelo próprio grupo.",
            "Com a fusão de cinquenta e sete bilhões de dólares entre lentes e armações, uma peça que custa doze dólares na linha de montagem chega à vitrine por trezentos dólares.",
            "No fim das contas, a concorrência que você vê na prateleira foi desenhada no mesmo escritório em Milão.",
        ],
        "narr_en": [
            "You walk into a mall and compare ten competing designer sunglasses brands thinking you have a choice — yet almost every frame comes from the exact same company.",
            "Over four decades, a single Italian giant quietly bought the frame factories, the luxury fashion licenses, and even the retail chains that sell them.",
            "When Oakley tried to fight back on pricing in 2001, its products were pulled from major stores until its stock plunged and it was acquired by the very same rival.",
            "Following a fifty-seven-billion-dollar merger uniting lenses and frames, an acetate piece costing twelve dollars to manufacture sells for over three hundred.",
            "What looks like fierce competition in the display case was engineered in a single boardroom in Milan.",
        ],
    },
    {
        "keywords": ("theranos", "holmes", "elizabeth", "sangue", "edison", "caixa vazia"),
        "title_pt": "Theranos: A Fraude de US$ 9 Bilhões dentro de uma Caixa Vazia",
        "title_en": "Theranos: The $9 Billion Silicon Valley Blood Mirage",
        "sub_pt": "Dossiê Vale do Silício • Projeto Edison",
        "sub_en": "Silicon Valley File • The Edison Black Box",
        "hook_pt": "CAIXA VAZIA",
        "hook_en": "IT WAS EMPTY",
        "origin": "PALO ALTO",
        "dest": "WASHINGTON D.C.",
        "metric_pt": "US$ 9 BILHÕES EVAPORADOS",
        "metric_en": "$9 BILLION VALUATION ZEROED",
        "headline": "SECRET LAB AUDIT EXPOSES COMMERCIAL ANALYZERS BEHIND THERANOS",
        "quote_pt": "Enquanto investidores avaliavam a empresa em US$ 9 bilhões, 94% dos testes reais eram rodados escondidos em máquinas comerciais de terceiros.",
        "quote_en": "While investors valued the startup at $9 billion, over 90% of patient tests were secretly run on diluted samples using third-party machines.",
        "timeline": [
            {"date": "2003", "label": "Fundação em Stanford", "value": "US$ 6M"},
            {"date": "2013", "label": "Acordo Farmácias", "value": "US$ 1.5B"},
            {"date": "2014", "label": "Pico de Valuation", "value": "US$ 9.0B"},
            {"date": "2018", "label": "Colapso & Indiciamento", "value": "US$ 0"},
        ],
        "nodes": [
            {"id": "n1", "title": "ELIZABETH HOLMES", "role": "CEO & Fundadora", "badge": "US$ 9 BILHÕES"},
            {"id": "n2", "title": "MÁQUINA EDISON", "role": "Promessa de 200 Exames", "badge": "FALHA TÉCNICA"},
            {"id": "n3", "title": "LAB SECRETO", "role": "Máquinas Comerciais", "badge": "AMOSTRAS DILUÍDAS"},
            {"id": "n4", "title": "DENÚNCIA WSJ", "role": "Investigação Forense", "badge": "COLAPSO TOTAL"},
        ],
        "narr_pt": [
            "Ela convenceu generais, ex-secretários de Estado e bilionários do Vale do Silício de que uma única gota de sangue faria duzentos exames — mas a máquina não funcionava.",
            "Documentos internos revelaram que quando os executivos visitavam a sede em Palo Alto, o aparelho Edison exibia apenas uma simulação pré-gravada na tela.",
            "Enquanto a empresa captava mais de setecentos milhões de dólares de investidores, as amostras reais eram levadas por uma porta trancada para máquinas comuns de mercado.",
            "Em 2015, um denunciante interno entregou os registros de laboratório à imprensa e aos reguladores federais, expondo resultados imprecisos em milhares de pacientes.",
            "Em poucos meses, o império de nove bilhões de dólares virou pó e entrou para a história como a maior ilusão corporativa do Vale do Silício.",
        ],
        "narr_en": [
            "She convinced four-star generals, former cabinet secretaries, and Silicon Valley billionaires that a single drop of blood could run two hundred tests — except the machine did not work.",
            "Internal records revealed that whenever VIP investors toured the Palo Alto headquarters, the Edison box on the desk was playing a pre-recorded software demo.",
            "While the company raised over seven hundred million dollars across private rounds, real blood samples were quietly routed through a locked basement to commercial analyzers.",
            "In 2015, a courageous lab whistleblower handed forensic logs to investigative reporters and regulators, exposing flawed results sent to real patients.",
            "Within months, a nine-billion-dollar unicorn evaporated into zero and became Silicon Valley's ultimate cautionary tale.",
        ],
    },
    {
        "keywords": ("evaldas", "rimasauskas", "boleto", "fatura", "quanta", "google", "facebook"),
        "title_pt": "O Homem que Enviou Boletos Falsos para o Vale do Silício — E Eles Pagaram",
        "title_en": "The Man Who Emailed Fake Invoices to Big Tech — And They Paid $122M",
        "sub_pt": "Dossiê Crimes Cibernéticos • Operação Quanta",
        "sub_en": "Cyber Forensics File • The $122M Invoice Scheme",
        "hook_pt": "ELES PAGARAM TUDO",
        "hook_en": "THEY JUST PAID",
        "origin": "VILNIUS",
        "dest": "VALE DO SILÍCIO",
        "metric_pt": "US$ 122 MILHÕES TRANSFERIDOS",
        "metric_en": "$122 MILLION WIRED",
        "headline": "LITHUANIAN SHELL COMPANY COLLECTS $122M FROM TECH GIANTS VIA EMAIL",
        "quote_pt": "Sem invadir nenhum servidor com código complexo, Rimasauskas registrou uma empresa homônima na Letônia e simplesmente enviou faturas por e-mail.",
        "quote_en": "Without deploying zero-day malware, Rimasauskas registered an identical supplier name in Latvia and emailed payment requests.",
        "timeline": [
            {"date": "2013", "label": "Empresa Homônima Criada", "value": "US$ 0"},
            {"date": "2014", "label": "Primeira Remessa Paga", "value": "US$ 23M"},
            {"date": "2015", "label": "Segunda Onda de Faturas", "value": "US$ 99M"},
            {"date": "2017", "label": "Rastreio Internacional", "value": "US$ 122M"},
        ],
        "nodes": [
            {"id": "n1", "title": "E. RIMASAUSKAS", "role": "Operador em Vilnius", "badge": "E-MAILS FALSOS"},
            {"id": "n2", "title": "QUANTA FICTÍCIA", "role": "Clone de Fornecedor Real", "badge": "LETÔNIA"},
            {"id": "n3", "title": "SETOR FINANCEIRO", "role": "Aprovação Automática", "badge": "US$ 122 MILHÕES"},
            {"id": "n4", "title": "6 PAÍSES", "role": "Bancos em Chipre e HK", "badge": "CONFISCADO"},
        ],
        "narr_pt": [
            "Ele não usou supercomputadores nem invadiu servidores secretos: ele apenas enviou boletos e faturas por e-mail para duas das maiores empresas de tecnologia do planeta — e elas pagaram cento e vinte e dois milhões de dólares.",
            "De um quarto na Lituânia, Evaldas Rimasauskas descobriu o nome exato de uma fabricante asiática que fornecia peças reais de servidores para o Vale do Silício.",
            "Ele abriu uma empresa com exatamente o mesmo nome na Letônia, falsificou carimbos simples e mandou e-mails cobrando lotes de hardware para o setor de contas a pagar.",
            "Durante dois anos, transferências milionárias saíram da Califórnia direto para contas na Europa Oriental, Chipre e Hong Kong sem ninguém checar o código bancário.",
            "Quando uma auditoria finalmente percebeu o erro de cento e vinte e dois milhões, o dinheiro já havia dado a volta ao mundo em seis jurisdições diferentes.",
        ],
        "narr_en": [
            "He did not write advanced malware or breach a firewall: he simply emailed invoices to two of the richest tech giants on Earth — and they wired him one hundred and twenty-two million dollars.",
            "From a quiet apartment in Lithuania, Evaldas Rimasauskas identified the exact Taiwanese hardware manufacturer supplying server racks to Silicon Valley.",
            "He incorporated a shell company with the exact same name in Latvia, forged basic stamps, and emailed billing requests straight to corporate accounts payable.",
            "For two full years, multi-million-dollar wires flowed from California into bank accounts across Latvia, Cyprus, and Hong Kong without triggering an alarm.",
            "By the time auditors noticed the one-hundred-and-twenty-two-million-dollar discrepancy, the funds had already been split across six international jurisdictions.",
        ],
    },
    {
        "keywords": ("camarão", "camarao", "red lobster", "infinito", "endless shrimp"),
        "title_pt": "O Dia em que o Camarão Infinito de US$ 20 Afundou uma Rede Bilionária",
        "title_en": "How $20 Endless Shrimp Sank a Billion-Dollar Restaurant Empire",
        "sub_pt": "Dossiê Corporativo • Colapso Red Lobster",
        "sub_en": "Corporate Autopsy • The Endless Shrimp Disaster",
        "hook_pt": "PREJUÍZO INFINITO",
        "hook_en": "INFINITE LOSS",
        "origin": "ORLANDO",
        "dest": "BANGKOK",
        "metric_pt": "-US$ 11 MILHÕES EM 90 DIAS",
        "metric_en": "-$11M OPERATING SHOCK",
        "headline": "PERMANENT $20 ENDLESS SHRIMP PROMOTION TRIGGERS CHAPTER 11 FILING",
        "quote_pt": "A fornecedora controladora transformou a promoção temporária de US$ 20 em item fixo do cardápio para escoar seu próprio estoque de camarão.",
        "quote_en": "Major supplier shareholders pushed to make the $20 promotion permanent while restaurant leases were already inflated.",
        "timeline": [
            {"date": "2014", "label": "Venda dos Imóveis (Leaseback)", "value": "US$ 1.5B"},
            {"date": "2020", "label": "Fornecedor Assume Controle", "value": "US$ 575M"},
            {"date": "2023", "label": "Camarão Infinito Fixo US$ 20", "value": "-US$ 11M"},
            {"date": "2024", "label": "Pedido de Recuperação Cap. 11", "value": "US$ 1B DÍVIDA"},
        ],
        "nodes": [
            {"id": "n1", "title": "PROMOÇÃO US$ 20", "role": "Camarão Sem Limite", "badge": "PREJUÍZO POR MESA"},
            {"id": "n2", "title": "LEASEBACK IMÓVEIS", "role": "Aluguel de US$ 200M/Ano", "badge": "CAIXA DRENADO"},
            {"id": "n3", "title": "FORNECEDOR GLOBAL", "role": "Escoamento de Estoque", "badge": "CONFLITO INTERNO"},
            {"id": "n4", "title": "CHAPTER 11", "role": "Mais de 100 Lojas Fechadas", "badge": "COLAPSO 2024"},
        ],
        "narr_pt": [
            "Parecia a promoção perfeita para atrair clientes: pague vinte dólares e coma camarão à vontade — só que os clientes aceitaram o desafio a sério demais.",
            "Em 2023, a tradicional rede americana Red Lobster decidiu transformar o festival temporário de camarão infinito em um prato fixo do cardápio todos os dias.",
            "Clientes passaram a ficar três horas na mesa e viralizaram no TikTok batendo recordes de mais de cem camarões por pessoa pagando apenas vinte dólares.",
            "Mas o verdadeiro golpe estava nos bastidores: anos antes, os terrenos das lojas haviam sido vendidos, obrigando a rede a pagar duzentos milhões por ano de aluguel.",
            "Somando aluguéis sufocantes com milhões de prejuízo no camarão, o império de setecentos restaurantes entrou em recuperação judicial com um bilhão em dívidas.",
        ],
        "narr_en": [
            "It sounded like the ultimate marketing hook: pay twenty dollars for all-you-can-eat shrimp — except hungry customers took the challenge literally.",
            "In 2023, restaurant giant Red Lobster made its temporary Endless Shrimp event a permanent everyday menu item at twenty dollars.",
            "Diners camped at tables for three hours and went viral on TikTok eating over a hundred shrimp on a single twenty-dollar bill.",
            "Yet the deeper trap lay behind the scenes: a prior sale-leaseback deal had stripped the company of its real estate, locking in two hundred million a year in rent.",
            "Crushed between soaring lease obligations and millions lost at the shrimp buffet, the seven-hundred-location chain filed for Chapter 11 with a billion dollars in debt.",
        ],
    },
    {
        "keywords": ("adidas", "puma", "irmãos", "irmaos", "dassler", "herzogenaurach"),
        "title_pt": "A Cidade Dividida ao Meio: A Guerra Secreta entre os Irmãos Adidas e Puma",
        "title_en": "Blood Rivals: How Two Feuding Brothers Split a Town into Adidas and Puma",
        "sub_pt": "Dossiê Histórico • Herzogenaurach, 1948",
        "sub_en": "Historical File • The Herzogenaurach Split",
        "hook_pt": "IRMÃOS INIMIGOS",
        "hook_en": "BLOOD RIVALS",
        "origin": "MARGEM NORTE",
        "dest": "MARGEM SUL",
        "metric_pt": "US$ 45 BILHÕES EM GUERRA",
        "metric_en": "$45B COMBINED RIVALRY",
        "headline": "TWO BROTHERS SPLIT ONE SHOE FACTORY ACROSS THE AURACH RIVER",
        "quote_pt": "Durante 60 anos, os moradores olhavam primeiro para os pés de um estranho antes de decidir se conversavam com ele.",
        "quote_en": "For six decades, townspeople looked down at a stranger's shoes before speaking a single word.",
        "timeline": [
            {"date": "1924", "label": "Fábrica Irmãos Dassler", "value": "1ª MEDALHA"},
            {"date": "1948", "label": "Ruptura & Rio Aurach", "value": "2 FÁBRICAS"},
            {"date": "1970", "label": "Pacto Pelé na Copa", "value": "QUEBRA DO ACORDO"},
            {"date": "2009", "label": "Primeira Trégua Oficial", "value": "61 ANOS DEPOIS"},
        ],
        "nodes": [
            {"id": "n1", "title": "ADI DASSLER", "role": "O Artesão Inventor", "badge": "FUNDOU A ADIDAS"},
            {"id": "n2", "title": "RUDI DASSLER", "role": "O Vendedor Agressivo", "badge": "FUNDOU A PUMA"},
            {"id": "n3", "title": "RIO AURACH", "role": "Fronteira na Cidade", "badge": "CIDADE DIVIDIDA"},
            {"id": "n4", "title": "COPA DE 1970", "role": "Pelé Amarra a Chuteira", "badge": "GOLPE DE MESTRE"},
        ],
        "narr_pt": [
            "Em uma pequena cidade da Alemanha, as pessoas aprenderam a olhar para os sapatos umas das outras antes de dar bom dia — porque dois irmãos declararam guerra total.",
            "Adi e Rudolf Dassler começaram fabricando calçados esportivos juntos na lavanderia da mãe em 1924, mas desconfianças na Segunda Guerra Mundial destruíram a família.",
            "Em 1948, eles dividiram os funcionários e as máquinas ao meio: Adi ficou de um lado do rio e criou a Adidas; Rudolf atravessou a ponte e fundou a Puma.",
            "A rivalidade explodiu na Copa de 1970, quando a Puma pagou a Pelé para pedir ao juiz alguns segundos antes do apito inicial e amarrar as chuteiras diante de todas as câmeras do mundo.",
            "Mesmo depois da morte dos dois irmãos, eles foram enterrados nas extremidades opostas do mesmo cemitério para nunca mais ficarem lado a lado.",
        ],
        "narr_en": [
            "In one small German town, residents learned to look down at a stranger's shoes before saying hello — because two brothers turned their family business into total war.",
            "Adi and Rudolf Dassler started cobbling track spikes together in their mother's laundry room in 1924, until bitter World War II suspicions tore them apart.",
            "In 1948, they split the factory assets down the middle: Adi stayed north of the river to launch Adidas, while Rudolf crossed the bridge to create Puma.",
            "The feud peaked at the 1970 World Cup, when Puma covertly paid Pelé to pause at kickoff and tie his boots in front of every television camera on Earth.",
            "Even in death, the two brothers were buried at opposite ends of the town cemetery so they would never rest side by side.",
        ],
    },
    {
        "keywords": ("pepsi", "caça", "caca", "harrier", "jato", "7.000.000", "leonard"),
        "title_pt": "O Estudante que Juntou 7 Milhões de Pontos e Exigiu o Caça Militar da Pepsi",
        "title_en": "The College Student Who Bought 7 Million Pepsi Points to Claim a Fighter Jet",
        "sub_pt": "Dossiê Jurídico • Leonard v. Pepsico (1996)",
        "sub_en": "Legal File • Leonard v. Pepsico, 7,000,000 Points",
        "hook_pt": "ELE JUNTOU OS PONTOS",
        "hook_en": "HE BOUGHT IT",
        "origin": "SEATTLE",
        "dest": "NOVA YORK",
        "metric_pt": "7.000.000 DE PONTOS",
        "metric_en": "7,000,000 PEPSI POINTS",
        "headline": "STUDENT SENDS $700,000 CHECK TO CLAIM HARRIER JET FROM TV COMMERCIAL",
        "quote_pt": "O regulamento impresso permitia comprar pontos extras por 10 centavos cada — transformando um caça de US$ 33 milhões em uma oferta de US$ 700 mil.",
        "quote_en": "Fine print in the catalog allowed buying extra points at 10 cents each — pricing a $33M Harrier Jet at just $700,000.",
        "timeline": [
            {"date": "1996", "label": "Comercial na TV sem Aviso", "value": "7.000.000 PTS"},
            {"date": "MAR/96", "label": "Descoberta da Brecha de US$ 0.10", "value": "US$ 700.000"},
            {"date": "MAI/96", "label": "Cheque Enviado à Pepsi", "value": "RECUSADO"},
            {"date": "1999", "label": "Sentença Federal em NY", "value": "CASO HISTÓRICO"},
        ],
        "nodes": [
            {"id": "n1", "title": "JOHN LEONARD", "role": "Estudante de 21 Anos", "badge": "DESCOBRIU A BRECHA"},
            {"id": "n2", "title": "TODD HOFFMAN", "role": "Investidor Anjo", "badge": "CHEQUE US$ 700K"},
            {"id": "n3", "title": "AV-8 HARRIER II", "role": "Caça de Pouso Vertical", "badge": "VALIA US$ 33M"},
            {"id": "n4", "title": "CATÁLOGO PEPSI", "role": "US$ 0,10 por Ponto Extra", "badge": "SEM LETRA MIÚDA"},
        ],
        "narr_pt": [
            "Em 1996, um comercial de televisão mostrou um caça militar Harrier de trinta e três milhões de dólares por sete milhões de pontos Pepsi sem nenhuma letra miúda na tela.",
            "Para juntar sete milhões de rótulos seria preciso beber dezenove mil latas por dia durante um ano — mas um estudante de vinte e um anos leu o catálogo até a última linha.",
            "No rodapé do formulário estava escrito que qualquer cliente podia ter apenas quinze pontos físicos e comprar o restante por dez centavos de dólar cada ponto.",
            "John Leonard fez a conta: sete milhões de pontos custavam exatamente setecentos mil dólares, então ele convenceu um investidor e enviou o cheque autenticado para a sede da empresa.",
            "A batalha judicial parou nos tribunais federais de Nova York e obrigou a indústria publicitária mundial a reescrever para sempre as regras de letras miúdas na TV.",
        ],
        "narr_en": [
            "In 1996, a television commercial flashed a thirty-three-million-dollar Harrier fighter jet for seven million Pepsi Points without a single disclaimer on screen.",
            "Collecting seven million physical labels meant drinking nineteen thousand sodas a day — until a twenty-one-year-old student read the printed catalog's final paragraph.",
            "Buried in the order rules was a clause allowing anyone with fifteen physical labels to purchase the remaining points for ten cents each.",
            "John Leonard did the math: seven million points cost exactly seven hundred thousand dollars, so he raised the money from an investor and mailed a certified check.",
            "The resulting federal lawsuit in New York became a landmark contract-law ruling that forever changed how television commercials write their disclaimers.",
        ],
    },
    {
        "keywords": ("wirecard", "marsalek", "fantasma", "2b", "2 bilhões", "alemanha", "dax"),
        "title_pt": "Wirecard: Os US$ 2 Bilhões Fantasmas que Enganaram a Europa Inteira",
        "title_en": "Wirecard: The $2 Billion Ghost Fortune That Fooled Europe",
        "sub_pt": "Dossiê Frankfurt & Manila • O Dinheiro Que Nunca Existiu",
        "sub_en": "Frankfurt & Manila File • The Missing €1.9 Billion",
        "hook_pt": "DINHEIRO FANTASMA",
        "hook_en": "GHOST BILLIONS",
        "origin": "MUNIQUE",
        "dest": "MANILA",
        "metric_pt": "US$ 2.1 BILHÕES INEXISTENTES",
        "metric_en": "$2.1 BILLION MISSING",
        "headline": "PHILIPPINE CENTRAL BANK CONFIRMS $2.1B WIRECARD ESCROW NEVER ENTERED COUNTRY",
        "quote_pt": "Um quarto de todo o lucro declarado pela gigante alemã do índice DAX estava supostamente guardado em duas contas asiáticas que nunca existiram.",
        "quote_en": "A quarter of the DAX-listed fintech's balance sheet sat inside two Philippine escrow accounts that turned out to be total fabrications.",
        "timeline": [
            {"date": "2018", "label": "Entrada no Índice DAX-30", "value": "US$ 28B"},
            {"date": "2019", "label": "Reportagens Financial Times", "value": "NEGADO"},
            {"date": "JUN/20", "label": "Bancos nas Filipinas Negam Saldo", "value": "-US$ 2.1B"},
            {"date": "JUL/20", "label": "Fuga de Marsalek & Falência", "value": "COLAPSO DAX"},
        ],
        "nodes": [
            {"id": "n1", "title": "WIRECARD AG", "role": "Estrela do Índice DAX-30", "badge": "VALIA US$ 28B"},
            {"id": "n2", "title": "JAN MARSALEK", "role": "COO & Operador Fantasma", "badge": "FORAGIDO"},
            {"id": "n3", "title": "BANCOS EM MANILA", "role": "Certificados Falsificados", "badge": "SALDO ZERO"},
            {"id": "n4", "title": "US$ 2.1 BILHÕES", "role": "Caixa Fictício Declarado", "badge": "NUNCA EXISTIU"},
        ],
        "narr_pt": [
            "Ela era a joia tecnológica da Alemanha, avaliada em vinte e oito bilhões de dólares no principal índice da bolsa de Frankfurt — até alguém ligar para dois bancos nas Filipinas.",
            "Durante anos, quando jornalistas questionavam a contabilidade da Wirecard, os reguladores protegiam a empresa e investigavam os próprios repórteres.",
            "No balanço oficial constavam dois vírgula um bilhões de dólares em dinheiro vivo guardados em contas fiduciárias na Ásia, representando quase todo o lucro acumulado do grupo.",
            "Em junho de 2020, auditores exigiram confirmação direta e o Banco Central das Filipinas respondeu com uma frase: esse dinheiro nunca entrou no nosso sistema financeiro.",
            "Em setenta e duas horas, o diretor de operações fugiu em um jato particular e a maior fintech da Europa declarou insolvência.",
        ],
        "narr_en": [
            "It was Germany's crown-jewel fintech, valued at twenty-eight billion dollars on Frankfurt's elite DAX index — until auditors finally called two banks in the Philippines.",
            "For years, whenever investigative reporters questioned Wirecard's profit margins, authorities defended the company and even probed the journalists.",
            "On paper, two point one billion dollars in cash sat safely inside Asian escrow accounts, representing nearly the entire historical profit of the enterprise.",
            "In June 2020, electronic verification was demanded and the Philippine Central Bank delivered a stunner: that money had never entered their financial system.",
            "Within seventy-two hours, the chief operating officer vanished on a private flight and Europe's premier tech champion collapsed into insolvency.",
        ],
    },
    {
        "keywords": ("forest city", "cidade fantasma", "100b", "100 bilhões", "malásia", "vazia", "98%"),
        "title_pt": "Forest City: A Metrópole Futurista de US$ 100 Bilhões que Está 98% Vazia",
        "title_en": "Forest City: Inside the $100 Billion Futuristic Megacity Sitting 98% Empty",
        "sub_pt": "Dossiê Megaprojetos • Estreito de Johor",
        "sub_en": "Megaproject File • The $100B Ghost Archipelago",
        "hook_pt": "98% VAZIA",
        "hook_en": "98% EMPTY",
        "origin": "SHENZHEN",
        "dest": "ESTREITO DE JOHOR",
        "metric_pt": "US$ 100 BILHÕES PROJETADOS",
        "metric_en": "$100B MEGAPROJECT STALLED",
        "headline": "FOUR ARTIFICIAL ISLANDS BUILT FOR 700,000 RESIDENTS STAND 98% UNINHABITED",
        "quote_pt": "Projetada para abrigar 700 mil pessoas em ilhas artificiais ao lado de Singapura, menos de 1% da capacidade foi ocupada após controles de capital.",
        "quote_en": "Engineered on reclaimed islands for 700,000 people across from Singapore, abrupt capital controls froze buyer inflows overnight.",
        "timeline": [
            {"date": "2016", "label": "Aterro de 4 Ilhas Artificiais", "value": "US$ 100B PLANO"},
            {"date": "2017", "label": "Limite de Remessas Externas", "value": "-85% VENDAS"},
            {"date": "2020", "label": "Fronteiras Fechadas", "value": "OBRAS PARADAS"},
            {"date": "2024", "label": "Menos de 9.000 Moradores", "value": "98% VAZIA"},
        ],
        "nodes": [
            {"id": "n1", "title": "FOREST CITY", "role": "Meta: 700.000 Habitantes", "badge": "4 ILHAS ARTIFICIAIS"},
            {"id": "n2", "title": "US$ 500K / APTO", "role": "Inacessível ao Mercado Local", "badge": "FOCO EXTERNO"},
            {"id": "n3", "title": "CONTROLE CAMBIAL", "role": "Teto de US$ 50K/Ano", "badge": "COMPRADORES TRAVADOS"},
            {"id": "n4", "title": "TORRES VAZIAS", "role": "Apenas ~2% de Ocupação", "badge": "CIDADE FANTASMA"},
        ],
        "narr_pt": [
            "Imagine construir quatro ilhas artificiais do zero, erguer dezenas de arranha-céus cobertos de florestas verticais por cem bilhões de dólares — e quase ninguém ir morar lá.",
            "Lançada em 2016 no sul da Malásia, a poucos minutos da fronteira com Singapura, Forest City foi planejada para receber setecentos mil moradores de alta renda.",
            "Só que os apartamentos custavam cinco vezes mais do que a classe média local podia pagar, pois todo o projeto dependia de compradores estrangeiros pagando à vista.",
            "Quando novos controles cambiais limitaram o envio de dinheiro para imóveis no exterior em cinquenta mil dólares por ano, as vendas secaram da noite para o dia.",
            "Hoje, avenidas de seis pistas, shoppings inteiros e dezenas de torres continuam com noventa e oito por cento dos apartamentos apagados no meio do oceano.",
        ],
        "narr_en": [
            "Imagine reclaiming four artificial islands from the sea and building dozens of jungle-wrapped skyscrapers under a hundred-billion-dollar masterplan — only for almost nobody to move in.",
            "Launched in 2016 at the southern tip of Malaysia looking straight across at Singapore, Forest City was engineered to house seven hundred thousand residents.",
            "Yet the luxury condos were priced far above local salaries, relying almost entirely on foreign buyers wiring capital from abroad.",
            "When sudden currency rules capped overseas property transfers at fifty thousand dollars a year, the buyer pipeline vanished overnight.",
            "Today, six-lane boulevards, sprawling shopping malls, and towers of luxury apartments sit ninety-eight percent dark above the ocean.",
        ],
    },
    {
        "keywords": ("pudim", "pudins", "pudding", "12.150", "milhas", "phillips", "engenheiro"),
        "title_pt": "O Engenheiro que Comprou 12.150 Pudins de US$ 0,25 e Ganhou Milhas Aéreas Vitalícias",
        "title_en": "The Engineer Who Bought 12,150 Cups of 25-Cent Pudding for Lifetime Frequent-Flyer Miles",
        "sub_pt": "Dossiê Arbitragem • A Brecha de 1,25 Milhão de Milhas",
        "sub_en": "Arbitrage File • The 1.25 Million Mile Loophole",
        "hook_pt": "BRECHA GENIAL",
        "hook_en": "THE PUDDING GLITCH",
        "origin": "DAVIS, CA",
        "dest": "MUNDO INTEIRO",
        "metric_pt": "1.253.000 MILHAS POR US$ 3.140",
        "metric_en": "1,253,000 MILES FOR $3,140",
        "headline": "CIVIL ENGINEER EXPLOITS 25-CENT PUDDING BARCODE PROMOTION FOR 1.25M AIR MILES",
        "quote_pt": "Ao doar os 12.150 potes para o banco de alimentos em troca de ajudar a retirar os códigos de barras, ele ainda abateu US$ 815 no imposto de renda.",
        "quote_en": "By donating all 12,150 pudding cups to charity in exchange for peeling the barcodes, he even earned an $815 tax deduction.",
        "timeline": [
            {"date": "MAI/99", "label": "Promoção 1.000 Milhas a Cada 10 Códigos", "value": "US$ 0.25 / POTE"},
            {"date": "JUN/99", "label": "Compra de 12.150 Potes de Pudim", "value": "US$ 3.140"},
            {"date": "JUL/99", "label": "Doação + Abatimento Fiscal", "value": "-US$ 815 IR"},
            {"date": "AGO/99", "label": "Crédito Final na Conta Aérea", "value": "1.253.000 MILHAS"},
        ],
        "nodes": [
            {"id": "n1", "title": "DAVID PHILLIPS", "role": "Engenheiro Civil", "badge": "CALCULOU A BRECHA"},
            {"id": "n2", "title": "12.150 PUDINS", "role": "US$ 0,25 por Unidade", "badge": "CUSTO US$ 3.140"},
            {"id": "n3", "title": "BANCO DE ALIMENTOS", "role": "Destacou os Códigos", "badge": "DEDUÇÃO FISCAL"},
            {"id": "n4", "title": "1,25 MILHÃO MILHAS", "role": "Equivalente a 31 Viagens", "badge": "VALIA US$ 150.000+"},
        ],
        "narr_pt": [
            "Em 1999, um engenheiro civil da Califórnia entrou em um supermercado, olhou para um potinho de pudim de vinte e cinco centavos e descobriu como viajar de primeira classe pelo resto da vida.",
            "Uma promoção da fabricante oferecia mil milhas aéreas para cada dez códigos de barras enviados até o fim do mês, achando que ninguém compraria centenas de caixas.",
            "David Phillips fez a conta na hora: dez potes custavam dois dólares e cinquenta centavos e rendiam mil milhas que valiam mais de vinte e cinco dólares em passagens.",
            "Ele esvaziou dez supermercados comprando doze mil cento e cinquenta pudins por três mil cento e quarenta dólares e doou toda a comida para uma instituição em troca de ajuda para descolar os rótulos.",
            "A empresa cumpriu a regra e depositou um milhão duzentas e cinquenta e três mil milhas na conta dele — uma fortuna em voos internacionais por uma fração do preço.",
        ],
        "narr_en": [
            "In 1999, a California civil engineer walked down a grocery aisle, spotted a twenty-five-cent cup of chocolate pudding, and discovered a mathematical path to lifetime flights.",
            "A promotional campaign offered one thousand frequent-flyer miles for every ten product barcodes mailed in by the end of the month.",
            "David Phillips ran the numbers on the spot: ten pudding cups cost two dollars and fifty cents yet generated one thousand air miles worth over twenty-five dollars.",
            "He swept through ten stores buying twelve thousand one hundred and fifty pudding cups for three thousand one hundred and forty dollars, then donated the food to charity in exchange for help peeling the labels.",
            "The company honored every barcode and deposited one million two hundred and fifty-three thousand air miles into his account — unlocking decades of free global travel.",
        ],
    },
]


def _build_universal_dossier(topic: str, lang: str = "pt_br") -> Dict[str, Any]:
    """Match one of the 10 signature investigative dossiers or synthesize a tailored dossier for any topic."""
    t_low = topic.lower()
    for d in _CURATED_DOSSIERS:
        if any(k in t_low for k in d["keywords"]):
            return d

    clean_t = _clean_doc_text(topic) or ("O Império Oculto do Capital" if lang == "pt_br" else "The Hidden Empire of Capital")
    short_upper = clean_t.upper()[:26]
    return {
        "keywords": (),
        "title_pt": f"Dossiê Confidencial: {clean_t}",
        "title_en": f"Classified File: {clean_t}",
        "sub_pt": "Investigação Forense • Arquivos do Capital",
        "sub_en": "Forensic Investigation • The Capital Vault",
        "hook_pt": "O SEGREDO OCULTO",
        "hook_en": "THE HIDDEN TRUTH",
        "origin": "ZURIQUE",
        "dest": "NOVA YORK",
        "metric_pt": "US$ 2.4 BILHÕES RASTREADOS",
        "metric_en": "$2.4 BILLION TRACED",
        "headline": f"FORENSIC AUDIT UNCOVERS HIDDEN LEDGERS BEHIND {short_upper}",
        "quote_pt": f"Registros confidenciais revelaram como a operação por trás de {clean_t} movimentou bilhões fora do radar público.",
        "quote_en": f"Declassified ledgers exposed how the architecture behind {clean_t} moved billions beneath public scrutiny.",
        "timeline": [
            {"date": "FASE I", "label": "Operação Silenciosa", "value": "US$ 18M"},
            {"date": "FASE II", "label": "Expansão Offshore", "value": "US$ 340M"},
            {"date": "FASE III", "label": "Pico de Alavancagem", "value": "US$ 2.4B"},
            {"date": "DESFECHO", "label": "Auditoria & Revelação", "value": "EXPOSTO"},
        ],
        "nodes": [
            {"id": "n1", "title": short_upper[:18], "role": "Operação Central", "badge": "ALVO #1"},
            {"id": "n2", "title": "HOLDING OFFSHORE", "role": "Blindagem Financeira", "badge": "CAIXA PRETA"},
            {"id": "n3", "title": "AUDITORIA FORENSE", "role": "Rastreamento Global", "badge": "US$ 2.4 BILHÕES"},
            {"id": "n4", "title": "IMPACTO DE MERCADO", "role": "Colapso do Esquema", "badge": "REVELADO"},
        ],
        "narr_pt": [
            f"Nos bastidores de {clean_t}, um único detalhe escondido nos relatórios oficiais mudou o destino de bilhões de dólares sem que o público percebesse.",
            f"Documentos de arquivo mostram que a engrenagem central de {clean_t} começou com uma brecha silenciosa que parecia impossível de rastrear.",
            "À medida que o capital cruzava fronteiras entre centros financeiros internacionais, cada transferência era camuflada em dezenas de contas intermediárias.",
            "Quando a linha do tempo completa veio à tona na auditoria forense, os números reais superavam em dez vezes qualquer estimativa oficial.",
            f"O caso de {clean_t} provou para sempre que no topo do mercado global nenhum segredo bilionário permanece enterrado para sempre.",
        ],
        "narr_en": [
            f"Behind the scenes of {clean_t}, a single anomaly buried inside official filings shifted billions of dollars before the public ever noticed.",
            f"Archival records reveal that the core mechanism driving {clean_t} began with a quiet loophole designed to stay invisible.",
            "As capital moved across international financial hubs, every wire was routed through layers of interconnected shell entities.",
            "When the complete chronological trail was reconstructed by forensic auditors, the real figures exceeded official estimates tenfold.",
            f"Ultimately, the story of {clean_t} proved that in high-stakes finance, no billion-dollar secret stays buried forever.",
        ],
    }


def generate_netflix_doc_plan(
    topic: str,
    aspect_ratio: str = "16:9",
    target_minutes: float = 0.5,
    lang: str = "pt_br",
) -> Dict[str, Any]:
    """Generate a complete investigative Netflix / MagnatesMedia documentary plan (dict).
    Supports both 16:9 Widescreen (1920x1080) and 9:16 Vertical Doc (1080x1920),
    scalable from quick 25s demos (target_minutes=0.5) up to 3-15 min mid-roll documentaries,
    in PT-BR ('Dossiê Capital') or EN-US ('Vault Files').
    """
    ar: Literal["16:9", "9:16"] = "9:16" if str(aspect_ratio).strip() == "9:16" else "16:9"
    clean_lang = "en_us" if str(lang).lower().startswith("en") else "pt_br"
    t_min = max(0.35, min(15.0, float(target_minutes or 0.5)))

    dossier = _build_universal_dossier(topic, lang=clean_lang)
    is_en = clean_lang == "en_us"
    channel_name = "Vault Files" if is_en else "Dossiê Capital"
    voice_id = "en-US-AndrewMultilingualNeural" if is_en else "pt-BR-AntonioNeural"
    title = dossier["title_en"] if is_en else dossier["title_pt"]
    subtitle = dossier["sub_en"] if is_en else dossier["sub_pt"]
    thumb_hook = dossier["hook_en"] if is_en else dossier["hook_pt"]
    base_narr = list(dossier["narr_en"] if is_en else dossier["narr_pt"])

    # Determine number of scenes based on target_minutes (~5.5s-6.5s per scene; minimum 5 scenes to showcase all 5 visual modes!)
    target_seconds = max(25.0, t_min * 60.0)
    n_scenes = max(5, min(90, int(round(target_seconds / 6.0))))

    # Optional LLM expansion when target_minutes > 1.0 and API key is configured
    settings = get_settings()
    dkey = (settings.get("deepseek_api_key") or "").strip()
    gkey = (settings.get("gemini_api_key") or "").strip()
    skill_path = SKILLS_DIR / "10_netflix_investigative_doc.md"
    skill_md = skill_path.read_text(encoding="utf-8")[:1200] if skill_path.exists() else ""

    if n_scenes > len(base_narr) and (dkey or gkey):
        sys_p = (
            f"You are an investigative documentary scriptwriter (Netflix / MagnatesMedia style) writing in {'American English' if is_en else 'Brazilian Portuguese'}. "
            f"Write exactly {n_scenes} gripping, factual narration paragraphs (18-26 words each) about '{title}'. "
            'Return ONLY valid JSON: {"lines":["..."]}'
        )
        try:
            if dkey:
                from openai import OpenAI

                cli = OpenAI(api_key=dkey, base_url="https://api.deepseek.com")
                resp = cli.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": f"TOPIC: {title}\n{skill_md}"}],
                    temperature=0.7,
                    max_tokens=min(4000, n_scenes * 75),
                    response_format={"type": "json_object"},
                )
                data = _extract_json(resp.choices[0].message.content or "{}")
                if isinstance(data.get("lines"), list) and len(data["lines"]) >= 5:
                    base_narr = [str(x).strip() for x in data["lines"][:n_scenes]]
                    u = resp.usage
                    record_token_usage("deepseek", "deepseek-flash", int(getattr(u, "prompt_tokens", 500)), int(getattr(u, "completion_tokens", 500)), 0, 0.0002)
        except Exception:
            pass

    # If offline or target_minutes > 0.6 requires more scenes than base_narr, expand deterministically with investigative depth
    while len(base_narr) < n_scenes:
        idx_add = len(base_narr)
        tp = dossier["timeline"][idx_add % len(dossier["timeline"])]
        nd = dossier["nodes"][idx_add % len(dossier["nodes"])]
        if is_en:
            base_narr.append(
                f"In {tp['date']}, forensic investigators cross-referenced {nd['title']} ({nd['role']}) and uncovered a critical milestone of {tp['value']} linked directly to {dossier['dest']}."
            )
        else:
            base_narr.append(
                f"Em {tp['date']}, os auditores forenses cruzaram os registros de {nd['title']} ({nd['role']}) e descobriram uma movimentação crítica de {tp['value']} conectada a {dossier['dest']}."
            )

    # Audit narrative lines with Retention Doctor principles (clean complete endings, zero debug words)
    audited = audit_viral_script_dict(
        {
            "title": title,
            "hook_a": base_narr[0],
            "hook_b": base_narr[0],
            "body_lines": base_narr[1:-1],
            "closing_line": base_narr[-1],
        }
    )
    final_narr = [audited["hook_a"], *audited["body_lines"], audited["closing_line"]]
    while len(final_narr) < 5:
        final_narr.append(base_narr[len(final_narr) % len(base_narr)])

    # Build scenes cycling through ALL 5 required investigative Skia C++ visual modes
    # Scene 0: Cold Open (parallax_25d_photo)
    # Scene 1: C A P Í T U L O   I (newspaper_highlighter)
    # Scene 2: dark_map_route
    # Scene 3: C A P Í T U L O   I I (sliding_timeline)
    # Scene 4: red_string_board
    chapter_chapter_subtitles_pt = [
        "A ANOMALIA NOS ARQUIVOS",
        "A ROTA DO CAPITAL OCULTO",
        "O PONTO DE RUPTURA",
        "O COLAPSO DO IMPÉRIO",
    ]
    chapter_chapter_subtitles_en = [
        "THE HIDDEN ANOMALY",
        "THE OFFSHORE MONEY TRAIL",
        "THE BREAKING POINT",
        "THE FINAL COLLAPSE",
    ]

    scenes: List[NetflixDocScene] = []
    chapter_counter = 0
    chapter_step = max(2, len(final_narr) // min(4, max(2, len(final_narr) // 2)))

    for idx, line_txt in enumerate(final_narr):
        vmode: VisualModeType = VISUAL_MODES[idx % len(VISUAL_MODES)]
        chap_card: Optional[str] = None
        chap_sub: Optional[str] = None

        if idx == 0:
            act_lbl = "COLD OPEN"
        elif idx == 1 or (idx >= 3 and (idx - 1) % chapter_step == 0 and chapter_counter < 4):
            roman = ROMAN_NUMERALS[min(chapter_counter, len(ROMAN_NUMERALS) - 1)]
            chap_card = _spaced_chapter_label(roman, lang=clean_lang)
            chap_sub = (chapter_chapter_subtitles_en if is_en else chapter_chapter_subtitles_pt)[
                min(chapter_counter, 3)
            ]
            act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"
            chapter_counter += 1
        else:
            roman = ROMAN_NUMERALS[max(0, min(chapter_counter - 1, len(ROMAN_NUMERALS) - 1))]
            act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"

        tp_cur = dossier["timeline"][idx % len(dossier["timeline"])]
        lt_title = f"{dossier['origin']} ➔ {dossier['dest']} • {tp_cur['date']}"
        lt_sub = f"{subtitle.upper()} • {tp_cur['value']}"

        scenes.append(
            NetflixDocScene(
                scene_id=f"doc_sc_{idx + 1:02d}",
                act_label=act_lbl,
                chapter_card=chap_card,
                chapter_subtitle=chap_sub,
                visual_mode=vmode,
                narration=_clean_doc_text(line_txt),
                lower_third_title=_clean_doc_text(lt_title),
                lower_third_subtitle=_clean_doc_text(lt_sub),
                highlight_color="#FFD166" if idx % 2 == 0 else "#FF2E93",
                evidence_headline=_clean_doc_text(dossier["headline"]),
                evidence_quote=_clean_doc_text(dossier["quote_en"] if is_en else dossier["quote_pt"]),
                map_origin=_clean_doc_text(dossier["origin"]),
                map_destination=_clean_doc_text(dossier["dest"]),
                map_metric=_clean_doc_text(dossier["metric_en"] if is_en else dossier["metric_pt"]),
                timeline_points=[TimelinePoint(**pt) for pt in dossier["timeline"]],
                board_nodes=[BoardNode(**nd) for nd in dossier["nodes"]],
                image_prompt_en=f"cinematic dark moody archival financial documentary photo {topic[:40]}",
            )
        )

    plan_obj = NetflixDocPlan(
        title=title,
        subtitle=subtitle,
        channel_name=channel_name,
        lang=clean_lang,
        aspect_ratio=ar,
        target_minutes=t_min,
        lut_file="02_dark_wealth.cube",
        voice_id=voice_id,
        thumbnail_hook=thumb_hook,
        scenes=scenes,
        hashtags=["#documentario", "#investigacao", "#financas", "#dossiecapital" if not is_en else "#vaultfiles"],
    )
    return plan_obj.model_dump()


# ---------------------------------------------------------------------------
# 3. Narrator Voice Synthesizer per Scene (PT-BR & EN-US + Exact WordBoundary)
# ---------------------------------------------------------------------------
async def _synthesize_doc_scene_narration(
    text: str,
    voice_id: str,
    lang: str,
    work_dir: Path,
    tag: str,
    thermal_limit_c: float = 85.0,
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Synthesize authoritative deep documentary narration for a single scene."""
    raw_mp3 = work_dir / f"{tag}_raw.mp3"
    raw_wav = work_dir / f"{tag}_raw.wav"
    vad_wav = work_dir / f"{tag}_vad.wav"

    default_v = "en-US-AndrewMultilingualNeural" if str(lang).lower().startswith("en") else "pt-BR-AntonioNeural"
    candidates = [voice_id or default_v, default_v, "pt-BR-AntonioNeural", "en-US-AndrewMultilingualNeural"]

    for v_try in candidates:
        try:
            comm = edge_tts.Communicate(
                text=text,
                voice=v_try,
                rate="+5%",
                pitch="-6Hz",
                boundary="WordBoundary",
            )
            words: List[Dict[str, Any]] = []
            chunks = bytearray()
            async for ch in comm.stream():
                if ch.get("type") == "audio":
                    chunks.extend(ch["data"])
                elif ch.get("type") == "WordBoundary":
                    st = float(ch["offset"]) / 10_000_000.0
                    dur = float(ch["duration"]) / 10_000_000.0
                    words.append({"word": str(ch["text"]).strip(), "start": round(st, 3), "end": round(st + max(0.06, dur), 3)})
            if chunks:
                raw_mp3.write_bytes(bytes(chunks))
                return trim_silence_vad(raw_mp3, vad_wav, words, thermal_limit_c=thermal_limit_c)
        except Exception:
            continue

    # Offline fallback via espeak-ng or pure-Python harmonic narration envelope
    try:
        _, words = _synthesize_espeak_fallback(text, raw_wav)
        return trim_silence_vad(raw_wav, vad_wav, words, thermal_limit_c=thermal_limit_c)
    except Exception:
        import numpy as np

        words = _estimate_word_timestamps(text, max(2.4, min(9.0, len(text.split()) * 0.36)))
        dur_est = round((words[-1]["end"] + 0.18) if words else 3.0, 3)
        sr = 48000
        t_arr = np.linspace(0.0, dur_est, int(sr * dur_est), endpoint=False, dtype=np.float32)
        env = np.zeros_like(t_arr)
        for wd in words:
            mask = (t_arr >= wd["start"]) & (t_arr <= wd["end"])
            if np.any(mask):
                w_t = (t_arr[mask] - wd["start"]) / max(0.05, wd["end"] - wd["start"])
                env[mask] = np.sin(np.pi * w_t) * (0.7 + 0.3 * np.sin(2.0 * np.pi * 3.5 * w_t))
        f0 = 112.0
        sig = env * (0.60 * np.sin(2.0 * np.pi * f0 * t_arr) + 0.28 * np.sin(2.0 * np.pi * f0 * 2.0 * t_arr) + 0.12 * np.sin(2.0 * np.pi * f0 * 3.0 * t_arr))
        pcm16 = np.clip(sig * 14000.0, -32000.0, 32000.0).astype(np.int16)
        stereo = np.column_stack([pcm16, pcm16])
        with wave.open(str(vad_wav), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(stereo.tobytes())
        return vad_wav, words, dur_est


# ---------------------------------------------------------------------------
# 4. Archival Image Cache + 5 Investigative Skia C++ Visual Mode Renderers
# ---------------------------------------------------------------------------
_ARCHIVAL_IMG_CACHE: Dict[str, Optional[skia.Image]] = {}


def _get_cached_archival_photo(prompt_en: str, w: int, h: int) -> Optional[skia.Image]:
    """Check local disk cache for an archival photo without blocking offline renders."""
    key = hashlib.sha256(f"{prompt_en}:{w}x{h}".encode("utf-8")).hexdigest()[:16]
    if key in _ARCHIVAL_IMG_CACHE:
        return _ARCHIVAL_IMG_CACHE[key]
    cache_path = DOC_BG_CACHE / f"doc_{w}x{h}_{key}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 15_000:
        try:
            img = skia.Image.open(str(cache_path))
            _ARCHIVAL_IMG_CACHE[key] = img
            return img
        except Exception:
            pass
    _ARCHIVAL_IMG_CACHE[key] = None
    return None


def _draw_obsidian_cinema_backdrop(canvas: skia.Canvas, w: int, h: int, t: float) -> None:
    """Draw rich dark wealth (#0B0713 -> #131126) backdrop with subtle investigative grid & projector dust."""
    bg = skia.Paint()
    bg.setShader(
        skia.GradientShader.MakeRadial(
            (w * 0.5, h * 0.42),
            max(w, h) * 0.78,
            [skia.ColorSetARGB(255, 24, 20, 44), skia.ColorSetARGB(255, 11, 7, 19)],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), bg)

    # Subtle forensic blueprint grid
    grid_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=skia.ColorSetARGB(18, 179, 136, 255))
    step = 96
    ox = int((t * 14.0) % step)
    for x in range(-ox, w + step, step):
        canvas.drawLine(x, 0, x, h, grid_p)
    for y in range(0, h + step, step):
        canvas.drawLine(0, y, w, y, grid_p)

    # Floating cinema projector dust motes
    dust_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(45, 255, 209, 102))
    for i in range(18):
        dx = ((i * 193 + t * (18 + (i % 5) * 6)) % w)
        dy = ((i * 137 - t * (12 + (i % 4) * 5)) % h)
        rad = 1.8 + (i % 3) * 1.1
        canvas.drawCircle(dx, dy, rad, dust_p)


def _draw_mode_parallax_25d_photo(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Mode A: Historical/archival photo with 2.5D depth parallax (background plate @ 0.60x + foreground subject card @ 1.25x) & vignette."""
    _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    is_wide = w >= h
    frame_w = w * (0.78 if is_wide else 0.86)
    frame_h = h * (0.56 if is_wide else 0.44)
    fx = (w - frame_w) * 0.5
    fy = h * (0.14 if is_wide else 0.16)

    # Layer 1: Background Archival Plate (0.60x slow Ken Burns zoom + pan)
    bg_zoom = 1.02 + 0.08 * prog
    bg_pan_x = (prog - 0.5) * -28.0
    canvas.save()
    canvas.translate(w * 0.5 + bg_pan_x, fy + frame_h * 0.5)
    canvas.scale(bg_zoom, bg_zoom)

    plate_r = skia.Rect.MakeXYWH(-frame_w * 0.5, -frame_h * 0.5, frame_w, frame_h)
    plate_bg = skia.Paint(AntiAlias=True)
    plate_bg.setShader(
        skia.GradientShader.MakeLinear(
            [(-frame_w * 0.5, -frame_h * 0.5), (frame_w * 0.5, frame_h * 0.5)],
            [skia.ColorSetARGB(255, 34, 30, 52), skia.ColorSetARGB(255, 18, 15, 30)],
        )
    )
    plate_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 36, 36, skia.ColorSetARGB(190, 0, 0, 0)))
    canvas.drawRoundRect(plate_r, 18, 18, plate_bg)

    arch_img = _get_cached_archival_photo(scene.image_prompt_en, int(frame_w), int(frame_h))
    canvas.save()
    canvas.clipRect(plate_r)
    if arch_img is not None:
        canvas.drawImageRect(arch_img, plate_r)
    else:
        # Procedural Archival Financial Photograph Plate (skyline/columns + halftone scanlines + sepia-gold duotone)
        col_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(42, 255, 209, 102))
        n_cols = 8
        cw = frame_w / (n_cols * 2.0)
        for ci in range(n_cols):
            cx = -frame_w * 0.42 + ci * (frame_w * 0.88 / n_cols)
            ch = frame_h * (0.38 + 0.28 * ((ci * 3 + 1) % 4) / 3.0)
            canvas.drawRect(skia.Rect.MakeXYWH(cx, frame_h * 0.45 - ch, cw, ch), col_p)

        # Archival waveform / financial index curve in background
        chart_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.0, Color=skia.ColorSetARGB(120, 179, 136, 255))
        cp = skia.Path()
        for xi in range(24):
            px = -frame_w * 0.48 + (xi / 23.0) * (frame_w * 0.96)
            py = frame_h * 0.10 - math.sin(xi * 0.55 + t * 0.8) * (frame_h * 0.16) - (xi / 23.0) * (frame_h * 0.14)
            if xi == 0:
                cp.moveTo(px, py)
            else:
                cp.lineTo(px, py)
        canvas.drawPath(cp, chart_p)

        # Subtle CRT/microfilm archival scanlines
        scan_p = skia.Paint(Color=skia.ColorSetARGB(22, 0, 0, 0))
        for sy in range(int(-frame_h * 0.5), int(frame_h * 0.5), 6):
            canvas.drawLine(-frame_w * 0.5, sy, frame_w * 0.5, sy, scan_p)
    canvas.restore()

    border_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=skia.ColorSetARGB(140, 255, 209, 102))
    canvas.drawRoundRect(plate_r, 18, 18, border_p)

    # Forensic viewfinder corner brackets
    brk_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5.0, Color=hex_to_skia(scene.highlight_color))
    bw_c = 36.0
    for sx_c in (-1, 1):
        for sy_c in (-1, 1):
            cx_c = sx_c * (frame_w * 0.5 - 18.0)
            cy_c = sy_c * (frame_h * 0.5 - 18.0)
            canvas.drawLine(cx_c, cy_c, cx_c - sx_c * bw_c, cy_c, brk_p)
            canvas.drawLine(cx_c, cy_c, cx_c, cy_c - sy_c * bw_c, brk_p)
    canvas.restore()

    # Layer 2: Foreground 2.5D Parallax Evidence Plate (moves at 1.35x relative parallax + higher scale)
    fg_pan_x = (prog - 0.5) * 44.0
    fg_zoom = 1.04 + 0.12 * prog
    card_w = min(frame_w * 0.82, w - 160.0)
    card_h = 215.0 if is_wide else 245.0

    canvas.save()
    canvas.translate(w * 0.5 + fg_pan_x, fy + frame_h * 0.54)
    canvas.scale(fg_zoom, fg_zoom)

    fg_rect = skia.Rect.MakeXYWH(-card_w * 0.5, -card_h * 0.5, card_w, card_h)
    fg_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(232, 14, 11, 26))
    fg_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 22, 38, 38, skia.ColorSetARGB(220, 0, 0, 0)))
    canvas.drawRoundRect(fg_rect, 20, 20, fg_bg)

    fg_border = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia(scene.highlight_color))
    canvas.drawRoundRect(fg_rect, 20, 20, fg_border)

    # Top forensic classification badge
    badge_txt = f"EVIDÊNCIA ARQUIVADA  •  {scene.act_label}"
    b_font, _ = _wrap_text_to_width(badge_txt, ui_tf, 22.0, 16.0, card_w - 80.0, 1)
    canvas.drawString(badge_txt, -card_w * 0.5 + 36.0, -card_h * 0.5 + 44.0, b_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

    # Auto-wrapped main forensic metric / headline inside foreground 2.5D card
    m_font, m_lines = _wrap_text_to_width(scene.map_metric, title_tf, 54.0, 30.0, card_w - 72.0, 2)
    my = -card_h * 0.5 + 108.0
    for ln in m_lines:
        canvas.drawString(ln, -card_w * 0.5 + 36.0, my, m_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
        my += m_font.getSize() * 1.15

    s_font, s_lines = _wrap_text_to_width(scene.evidence_headline, ui_tf, 24.0, 17.0, card_w - 72.0, 1)
    if s_lines:
        canvas.drawString(s_lines[0], -card_w * 0.5 + 36.0, card_h * 0.5 - 28.0, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 230, 225, 245)))

    canvas.restore()


def _draw_mode_newspaper_highlighter(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Mode B: Newspaper/document clipping with animated Multiply-blend highlighter sweep in Gold (#FFD166) or Pink (#FF2E93)."""
    _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    is_wide = w >= h
    paper_w = min(w - 140.0, 1340.0 if is_wide else 900.0)
    paper_h = h * (0.56 if is_wide else 0.46)
    px = (w - paper_w) * 0.5
    py = h * (0.13 if is_wide else 0.16)

    # Slow 2.5D editorial camera push-in
    cam_scale = 1.0 + 0.06 * prog
    tilt_deg = -1.2 + 0.9 * prog

    canvas.save()
    canvas.translate(w * 0.5, py + paper_h * 0.5)
    canvas.scale(cam_scale, cam_scale)
    canvas.rotate(tilt_deg)

    p_rect = skia.Rect.MakeXYWH(-paper_w * 0.5, -paper_h * 0.5, paper_w, paper_h)
    paper_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 244, 238, 224))
    paper_paint.setImageFilter(skia.ImageFilters.DropShadow(0, 22, 42, 42, skia.ColorSetARGB(215, 0, 0, 0)))
    canvas.drawRoundRect(p_rect, 12, 12, paper_paint)

    ink_dark = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 22, 18, 28))
    ink_muted = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(170, 68, 62, 74))
    rule_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=skia.ColorSetARGB(255, 38, 32, 44))

    left_x = -paper_w * 0.5 + 48.0
    right_x = paper_w * 0.5 - 48.0
    inner_w = paper_w - 96.0
    top_y = -paper_h * 0.5 + 46.0

    # Masthead: THE FINANCIAL DOSSIER • SPECIAL FORENSIC EDITION
    mast_txt = "THE FINANCIAL DOSSIER   •   FORENSIC ARCHIVE EDITION"
    mast_font, _ = _wrap_text_to_width(mast_txt, ui_tf, 22.0, 15.0, inner_w, 1)
    canvas.drawString(mast_txt, left_x, top_y, mast_font, ink_muted)
    canvas.drawLine(left_x, top_y + 14.0, right_x, top_y + 14.0, rule_p)
    canvas.drawLine(left_x, top_y + 20.0, right_x, top_y + 20.0, rule_p)

    # Bold Newspaper Headline (auto-wrapped to 2 lines, never clips)
    h_font, h_lines = _wrap_text_to_width(scene.evidence_headline.upper(), title_tf, 46.0, 26.0, inner_w, 2)
    hy = top_y + 72.0
    for ln in h_lines:
        canvas.drawString(ln, left_x, hy, h_font, ink_dark)
        hy += h_font.getSize() * 1.18

    canvas.drawLine(left_x, hy - 14.0, right_x, hy - 14.0, rule_p)

    # Decorative faux newspaper text columns in background
    col_line_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6.0, Color=skia.ColorSetARGB(42, 40, 35, 48))
    for cy_f in range(int(hy + 12), int(paper_h * 0.5 - 32), 18):
        canvas.drawLine(left_x, cy_f, left_x + inner_w * 0.46, cy_f, col_line_p)
        canvas.drawLine(left_x + inner_w * 0.52, cy_f, right_x, cy_f, col_line_p)

    # Key Evidence Quote Box with Animated Multiply-Blend Highlighter Sweep (#FFD166 or #FF2E93)
    q_font, q_lines = _wrap_text_to_width(scene.evidence_quote, ui_tf, 32.0, 20.0, inner_w - 40.0, 3)
    q_box_y = hy + 28.0
    line_step = q_font.getSize() * 1.38
    q_box_h = len(q_lines) * line_step + 36.0

    # Clean cream callout box over faux columns
    callout_r = skia.Rect.MakeXYWH(left_x, q_box_y, inner_w, min(q_box_h, paper_h * 0.5 - q_box_y - 24.0))
    canvas.drawRoundRect(callout_r, 10, 10, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(248, 250, 246, 235)))
    canvas.drawRoundRect(callout_r, 10, 10, rule_p)

    # Sweep progress across the quote lines (0.0 -> 1.0 over first 70% of scene)
    sweep_total = _ease_out_cubic(min(1.0, max(0.0, (prog - 0.06) / 0.68)))
    hl_hex = scene.highlight_color if scene.highlight_color in ("#FFD166", "#FF2E93") else "#FFD166"
    # High-visibility highlighter ink with Multiply blend mode so black newspaper print stays razor sharp!
    hl_color = hex_to_skia(hl_hex, alpha=210 if hl_hex == "#FFD166" else 175)
    hl_paint = skia.Paint(AntiAlias=True, Color=hl_color)
    hl_paint.setBlendMode(skia.BlendMode.kMultiply)

    n_lns = max(1, len(q_lines))
    qy = q_box_y + 42.0
    for idx_l, qln in enumerate(q_lines):
        # First draw the dark newspaper print text
        canvas.drawString(qln, left_x + 20.0, qy, q_font, ink_dark)
        # Then sweep the Multiply-blend highlighter marker over this line
        line_prog = max(0.0, min(1.0, sweep_total * n_lns - idx_l))
        if line_prog > 0.01:
            lw = float(q_font.measureText(qln))
            hl_rect = skia.Rect.MakeXYWH(
                left_x + 12.0,
                qy - q_font.getSize() * 0.88,
                (lw + 16.0) * line_prog,
                q_font.getSize() * 1.16,
            )
            canvas.drawRoundRect(hl_rect, 8, 8, hl_paint)
        qy += line_step

    canvas.restore()


def _draw_mode_dark_map_route(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Mode C: Dark investigative world/city map with animated dashed route & glowing destination pin."""
    _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    is_wide = w >= h
    map_w = w * (0.82 if is_wide else 0.88)
    map_h = h * (0.56 if is_wide else 0.46)
    mx = (w - map_w) * 0.5
    my = h * (0.13 if is_wide else 0.16)

    map_r = skia.Rect.MakeXYWH(mx, my, map_w, map_h)
    map_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(235, 13, 18, 36))
    map_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 36, 36, skia.ColorSetARGB(200, 0, 0, 0)))
    canvas.drawRoundRect(map_r, 24, 24, map_bg)

    canvas.save()
    canvas.clipRect(map_r)

    # Stylized dark vector continents / landmass silhouettes
    land_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(95, 34, 48, 84))
    land_stroke = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=skia.ColorSetARGB(120, 76, 106, 175))
    for cx_f, cy_f, rx_f, ry_f in [
        (0.22, 0.36, 0.14, 0.18),
        (0.28, 0.68, 0.09, 0.16),
        (0.50, 0.34, 0.13, 0.15),
        (0.54, 0.62, 0.11, 0.17),
        (0.76, 0.42, 0.16, 0.19),
    ]:
        oval = skia.Rect.MakeXYWH(mx + map_w * (cx_f - rx_f), my + map_h * (cy_f - ry_f), map_w * rx_f * 2, map_h * ry_f * 2)
        canvas.drawRoundRect(oval, 42, 42, land_p)
        canvas.drawRoundRect(oval, 42, 42, land_stroke)

    # Tactical radar concentric rings
    p_orig = (mx + map_w * 0.22, my + map_h * 0.60)
    p_dest = (mx + map_w * 0.78, my + map_h * 0.36)
    p_ctrl = (mx + map_w * 0.50, my + map_h * 0.12)

    ring_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.5, Color=skia.ColorSetARGB(70, 255, 46, 147))
    for rad in (36.0, 72.0, 112.0):
        pulse_r = rad + ((t * 28.0) % 36.0)
        canvas.drawCircle(p_dest[0], p_dest[1], pulse_r, ring_p)

    # Animated progressive dashed route from p_orig -> p_dest along quadratic Bézier
    route_prog = _ease_out_cubic(min(1.0, max(0.05, prog * 1.25)))
    route_path = skia.Path()
    steps = 48
    max_step = max(2, int(steps * route_prog))
    cur_tip = p_orig
    for si in range(max_step + 1):
        u = si / float(steps)
        bx = ((1 - u) ** 2) * p_orig[0] + 2 * (1 - u) * u * p_ctrl[0] + (u ** 2) * p_dest[0]
        by = ((1 - u) ** 2) * p_orig[1] + 2 * (1 - u) * u * p_ctrl[1] + (u ** 2) * p_dest[1]
        if si == 0:
            route_path.moveTo(bx, by)
        else:
            route_path.lineTo(bx, by)
        cur_tip = (bx, by)

    # Glowing pink/gold dashed line
    glow_route = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=10.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(110, 255, 46, 147),
    )
    glow_route.setImageFilter(skia.ImageFilters.Blur(6, 6))
    canvas.drawPath(route_path, glow_route)

    dash_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=5.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#FFD166"),
    )
    dash_p.setPathEffect(skia.DashPathEffect.Make([18.0, 12.0], -t * 70.0))
    canvas.drawPath(route_path, dash_p)

    # Origin Pin + Label
    canvas.drawCircle(p_orig[0], p_orig[1], 12.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B388FF")))
    canvas.drawCircle(p_orig[0], p_orig[1], 6.0, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
    o_font, o_lines = _wrap_text_to_width(scene.map_origin.upper(), title_tf, 28.0, 18.0, map_w * 0.34, 1)
    if o_lines:
        canvas.drawString(o_lines[0], p_orig[0] - 24.0, p_orig[1] + 42.0, o_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

    # Glowing Destination Pin + Pulsing Beacon
    pin_pulse = 14.0 + 5.0 * math.sin(t * 8.0)
    pin_glow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(140, 255, 46, 147))
    pin_glow.setImageFilter(skia.ImageFilters.Blur(8, 8))
    canvas.drawCircle(p_dest[0], p_dest[1], pin_pulse * 1.7, pin_glow)
    canvas.drawCircle(p_dest[0], p_dest[1], pin_pulse, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93")))
    canvas.drawCircle(p_dest[0], p_dest[1], 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))
    canvas.drawCircle(cur_tip[0], cur_tip[1], 8.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

    d_font, d_lines = _wrap_text_to_width(scene.map_destination.upper(), title_tf, 30.0, 18.0, map_w * 0.34, 1)
    if d_lines:
        dw = d_font.measureText(d_lines[0])
        dx_lbl = min(mx + map_w - dw - 28.0, max(mx + 24.0, p_dest[0] - dw * 0.5))
        canvas.drawString(d_lines[0], dx_lbl, p_dest[1] + 44.0, d_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

    # Top-left HUD Metric Banner inside map
    hud_w = min(map_w - 64.0, 560.0)
    hud_r = skia.Rect.MakeXYWH(mx + 28.0, my + 24.0, hud_w, 86.0)
    canvas.drawRoundRect(hud_r, 14, 14, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 11, 7, 19)))
    canvas.drawRoundRect(hud_r, 14, 14, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#B8FF01")))
    m_font, m_lines = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 32.0, 20.0, hud_w - 36.0, 1)
    if m_lines:
        canvas.drawString(m_lines[0], mx + 46.0, my + 78.0, m_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))
    sub_hud = skia.Font(ui_tf, 16.0)
    canvas.drawString("RASTREAMENTO FORENSE DE FLUXO", mx + 46.0, my + 46.0, sub_hud, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(200, 179, 136, 255)))

    canvas.restore()
    canvas.drawRoundRect(map_r, 24, 24, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#B388FF", 160)))


def _draw_mode_sliding_timeline(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Mode D: Horizontal (16:9) or Vertical (9:16) sliding timeline of dates & financial figures."""
    _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    pts = scene.timeline_points or [
        TimelinePoint(date="FASE I", label="Origem", value="US$ 10M"),
        TimelinePoint(date="FASE II", label="Escalada", value="US$ 240M"),
        TimelinePoint(date="FASE III", label="Colapso", value="US$ 1.4B"),
    ]
    n_pts = len(pts)
    active_float = prog * max(1, n_pts - 1)
    active_idx = min(n_pts - 1, int(round(active_float)))
    is_wide = w >= h

    if is_wide:
        # Horizontal camera-sliding timeline across 1920x1080 canvas
        rail_y = h * 0.40
        slot_spacing = 460.0
        cam_x = w * 0.5 - active_float * slot_spacing

        canvas.save()
        # Horizontal glowing timeline rail
        canvas.drawLine(80.0, rail_y, w - 80.0, rail_y, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.0, Color=skia.ColorSetARGB(90, 179, 136, 255)))
        fill_x = 80.0 + (w - 160.0) * _ease_out_cubic(prog)
        canvas.drawLine(80.0, rail_y, fill_x, rail_y, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6.0, Color=hex_to_skia("#FFD166")))

        for idx, pt in enumerate(pts):
            nx = cam_x + idx * slot_spacing
            if nx < -260.0 or nx > w + 260.0:
                continue
            is_act = idx == active_idx
            card_w = 380.0
            card_h = 220.0
            cy_card = rail_y - 265.0 if idx % 2 == 0 else rail_y + 48.0

            # Node circle on rail
            canvas.drawCircle(nx, rail_y, 18.0 if is_act else 11.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93" if is_act else "#B388FF")))
            canvas.drawCircle(nx, rail_y, 7.0, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            # Milestone Card clamped inside horizontal safe zone when near edges
            cx_card = max(60.0, min(w - card_w - 60.0, nx - card_w * 0.5))
            c_rect = skia.Rect.MakeXYWH(cx_card, cy_card, card_w, card_h)
            c_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(235 if is_act else 185, 18, 14, 34))
            c_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 14, 28, 28, skia.ColorSetARGB(180, 0, 0, 0)))
            canvas.drawRoundRect(c_rect, 18, 18, c_bg)
            b_col = hex_to_skia("#FFD166" if is_act else "#B388FF", 240 if is_act else 110)
            canvas.drawRoundRect(c_rect, 18, 18, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.5 if is_act else 2.0, Color=b_col))

            # Date badge
            d_font, d_lns = _wrap_text_to_width(pt.date.upper(), title_tf, 32.0, 20.0, card_w - 48.0, 1)
            if d_lns:
                canvas.drawString(d_lns[0], cx_card + 24.0, cy_card + 48.0, d_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01" if is_act else "#B388FF")))

            # Financial Value
            v_font, v_lns = _wrap_text_to_width(pt.value.upper(), title_tf, 46.0, 26.0, card_w - 48.0, 1)
            if v_lns:
                canvas.drawString(v_lns[0], cx_card + 24.0, cy_card + 114.0, v_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

            # Event Label
            l_font, l_lns = _wrap_text_to_width(pt.label, ui_tf, 24.0, 16.0, card_w - 48.0, 2)
            ly = cy_card + 162.0
            for lln in l_lns:
                canvas.drawString(lln, cx_card + 24.0, ly, l_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                ly += 28.0
        canvas.restore()
    else:
        # Vertical sliding timeline for 9:16 Doc (1080x1920)
        rail_x = 130.0
        top_y = h * 0.16
        slot_h = 195.0
        canvas.drawLine(rail_x, top_y, rail_x, top_y + slot_h * (n_pts - 0.5), skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5.0, Color=hex_to_skia("#FFD166")))
        for idx, pt in enumerate(pts[:4]):
            ny = top_y + idx * slot_h
            is_act = idx == active_idx
            canvas.drawCircle(rail_x, ny + 55.0, 16.0 if is_act else 10.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93" if is_act else "#B388FF")))
            card_w = w - 240.0
            c_rect = skia.Rect.MakeXYWH(rail_x + 42.0, ny, card_w, 160.0)
            canvas.drawRoundRect(c_rect, 18, 18, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 18, 14, 34)))
            canvas.drawRoundRect(c_rect, 18, 18, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#FFD166" if is_act else "#B388FF")))
            d_font, _ = _wrap_text_to_width(f"{pt.date}  •  {pt.value}", title_tf, 34.0, 22.0, card_w - 48.0, 1)
            canvas.drawString(f"{pt.date}  •  {pt.value}", rail_x + 66.0, ny + 62.0, d_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            l_font, l_lns = _wrap_text_to_width(pt.label, ui_tf, 26.0, 18.0, card_w - 48.0, 1)
            if l_lns:
                canvas.drawString(l_lns[0], rail_x + 66.0, ny + 118.0, l_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))


def _draw_mode_red_string_board(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Mode E: Investigative cork/obsidian board connecting suspects/companies/evidence nodes with glowing red/pink strings (#FF2E93)."""
    _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    nodes = (scene.board_nodes or [
        BoardNode(id="n1", title="SUSPEITO #1", role="Operador Central", badge="ALVO"),
        BoardNode(id="n2", title="CONTA OCULTA", role="Offshore", badge="CAIXA PRETA"),
        BoardNode(id="n3", title="AUDITORIA", role="Relatório Forense", badge="PROVA"),
        BoardNode(id="n4", title="COLAPSO", role="Impacto Global", badge="DESFECHO"),
    ])[:4]

    is_wide = w >= h
    if is_wide:
        centers = [
            (w * 0.25, h * 0.25),
            (w * 0.75, h * 0.24),
            (w * 0.27, h * 0.56),
            (w * 0.73, h * 0.55),
        ]
        card_w, card_h = 460.0, 195.0
    else:
        centers = [
            (w * 0.50, h * 0.19),
            (w * 0.50, h * 0.34),
            (w * 0.50, h * 0.49),
            (w * 0.50, h * 0.64),
        ]
        card_w, card_h = w - 180.0, 155.0

    pin_coords = [(cx, cy - card_h * 0.5 + 18.0) for (cx, cy) in centers[: len(nodes)]]

    # 1. Draw Evidence Cards first so glowing red/pink strings (#FF2E93) connect pin-to-pin on top!
    for idx, nd in enumerate(nodes):
        cx, cy = centers[idx]
        rx = cx - card_w * 0.5
        ry = cy - card_h * 0.5
        c_rect = skia.Rect.MakeXYWH(rx, ry, card_w, card_h)

        bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(238, 19, 15, 36))
        bg.setImageFilter(skia.ImageFilters.DropShadow(0, 16, 30, 30, skia.ColorSetARGB(210, 0, 0, 0)))
        canvas.drawRoundRect(c_rect, 18, 18, bg)

        b_col = hex_to_skia("#FF2E93" if idx % 2 == 0 else "#FFD166")
        canvas.drawRoundRect(c_rect, 18, 18, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=b_col))

        # Top badge pill
        b_font, b_lns = _wrap_text_to_width(nd.badge.upper(), ui_tf, 20.0, 14.0, card_w - 64.0, 1)
        if b_lns:
            canvas.drawString(b_lns[0], rx + 26.0, ry + 42.0, b_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

        # Node Title
        t_font, t_lns = _wrap_text_to_width(nd.title.upper(), title_tf, 36.0, 22.0, card_w - 52.0, 1)
        if t_lns:
            canvas.drawString(t_lns[0], rx + 26.0, ry + 96.0, t_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

        # Role Subtitle
        r_font, r_lns = _wrap_text_to_width(nd.role, ui_tf, 23.0, 16.0, card_w - 52.0, 1)
        if r_lns:
            canvas.drawString(r_lns[0], rx + 26.0, ry + 144.0, r_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

    # 2. Draw Glowing Red/Pink Investigative Strings (#FF2E93) connecting the pins!
    edges = [(0, 1), (0, 2), (1, 3), (2, 3), (1, 2)]
    str_glow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=11.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(120, 255, 46, 147),
    )
    str_glow.setImageFilter(skia.ImageFilters.Blur(7, 7))
    str_core = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=4.5,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#FF2E93"),
    )

    for e_idx, (i0, i1) in enumerate(edges):
        if i0 >= len(pin_coords) or i1 >= len(pin_coords):
            continue
        p0 = pin_coords[i0]
        p1 = pin_coords[i1]
        edge_prog = _ease_out_cubic(min(1.0, max(0.15, (prog * 1.4) - e_idx * 0.12)))
        mx_e = p0[0] + (p1[0] - p0[0]) * edge_prog
        my_e = p0[1] + (p1[1] - p0[1]) * edge_prog
        ctrl_x = (p0[0] + mx_e) * 0.5
        ctrl_y = (p0[1] + my_e) * 0.5 + 26.0

        sp = skia.Path()
        sp.moveTo(p0[0], p0[1])
        sp.quadTo(ctrl_x, ctrl_y, mx_e, my_e)
        canvas.drawPath(sp, str_glow)
        canvas.drawPath(sp, str_core)

    # Metallic Thumbtacks on each pin
    for px_p, py_p in pin_coords:
        canvas.drawCircle(px_p, py_p, 11.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93")))
        canvas.drawCircle(px_p - 2.0, py_p - 2.0, 4.0, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))


# ---------------------------------------------------------------------------
# 5. Sleek Chapter Cards, Lower Thirds & Widescreen Cinema Subtitles
# ---------------------------------------------------------------------------
def _draw_chapter_card_overlay(
    canvas: skia.Canvas,
    w: int,
    h: int,
    chapter_title: str,
    chapter_subtitle: str,
    local_t: float,
    chapter_dur: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Render full-screen Netflix / MagnatesMedia wide letter-spaced Chapter Card ('C A P Í T U L O   I')."""
    fade_in = _ease_out_cubic(local_t / 0.25)
    fade_out = _ease_out_cubic((chapter_dur - local_t) / 0.28) if (chapter_dur - local_t) < 0.28 else 1.0
    alpha = int(255 * min(fade_in, fade_out))
    if alpha <= 6:
        return

    canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=skia.ColorSetARGB(int(alpha * 0.94), 9, 6, 16)))

    # Expanding golden horizontal cinema divider lines
    line_w = (w * 0.46) * _ease_out_cubic(local_t / 0.75)
    line_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=skia.ColorSetARGB(alpha, 255, 209, 102))
    canvas.drawLine(w * 0.5 - line_w * 0.5, h * 0.43, w * 0.5 + line_w * 0.5, h * 0.43, line_p)
    canvas.drawLine(w * 0.5 - line_w * 0.5, h * 0.59, w * 0.5 + line_w * 0.5, h * 0.59, line_p)

    # Wide letter-spaced C A P Í T U L O   I
    c_font, c_lns = _wrap_text_to_width(chapter_title, title_tf, 58.0, 28.0, w - 160.0, 1)
    if c_lns:
        cw = c_font.measureText(c_lns[0])
        cp = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 209, 102))
        cp.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 24, 24, skia.ColorSetARGB(int(alpha * 0.65), 255, 209, 102)))
        canvas.drawString(c_lns[0], (w - cw) * 0.5, h * 0.39, c_font, cp)

    if chapter_subtitle:
        s_font, s_lns = _wrap_text_to_width(chapter_subtitle.upper(), ui_tf, 42.0, 24.0, w - 180.0, 1)
        if s_lns:
            sw = s_font.measureText(s_lns[0])
            canvas.drawString(s_lns[0], (w - sw) * 0.5, h * 0.53, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 255, 255)))


def _draw_sleek_lower_third(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    local_t: float,
    scene_dur: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Draw sleek investigative documentary Lower Third (top-left in 9:16 or bottom-left above subtitles in 16:9)."""
    enter = _ease_out_cubic(local_t / 0.35)
    exit_a = _ease_out_cubic((scene_dur - local_t) / 0.30) if (scene_dur - local_t) < 0.30 else 1.0
    alpha = int(240 * min(enter, exit_a))
    if alpha <= 10:
        return

    is_wide = w >= h
    box_w = min(w - 140.0, 620.0 if is_wide else 860.0)
    box_h = 92.0
    bx = 72.0 + (1.0 - enter) * -32.0
    by = h * 0.725 if is_wide else 76.0

    r = skia.Rect.MakeXYWH(bx, by, box_w, box_h)
    bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.88), 12, 9, 22))
    bg.setImageFilter(skia.ImageFilters.DropShadow(0, 10, 20, 20, skia.ColorSetARGB(int(alpha * 0.7), 0, 0, 0)))
    canvas.drawRoundRect(r, 14, 14, bg)

    # Vertical glowing accent bar on left edge
    bar_r = skia.Rect.MakeXYWH(bx, by + 10.0, 8.0, box_h - 20.0)
    canvas.drawRoundRect(bar_r, 4, 4, skia.Paint(AntiAlias=True, Color=hex_to_skia(scene.highlight_color, alpha)))

    t_font, t_lns = _wrap_text_to_width(scene.lower_third_title.upper(), title_tf, 26.0, 17.0, box_w - 44.0, 1)
    if t_lns:
        canvas.drawString(t_lns[0], bx + 26.0, by + 40.0, t_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", alpha)))

    s_font, s_lns = _wrap_text_to_width(scene.lower_third_subtitle.upper(), ui_tf, 19.0, 14.0, box_w - 44.0, 1)
    if s_lns:
        canvas.drawString(s_lns[0], bx + 26.0, by + 72.0, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 218, 212, 238)))


def _draw_doc_subtitles(
    canvas: skia.Canvas,
    w: int,
    h: int,
    chunks: List[Dict[str, Any]],
    t: float,
    caption_tf: skia.Typeface,
) -> None:
    """Render clean documentary subtitles with custom-fitted active word pill and guaranteed zero edge clipping."""
    is_wide = w >= h
    base_size = 58.0 if is_wide else 72.0
    cap_font = skia.Font(caption_tf, base_size)
    space_w = max(24.0, float(cap_font.measureText(" ")) * 1.42)
    fm = cap_font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    # Contrast lower-third scrim
    scrim = skia.Paint()
    scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0, h * 0.78), (0, h)],
            [skia.ColorSetARGB(0, 11, 7, 19), skia.ColorSetARGB(205, 11, 7, 19)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(0, h * 0.78, w, h * 0.22), scrim)

    for ch in chunks:
        if ch["start"] <= t <= ch["end"]:
            w_list = ch["words"]
            active_wd = next((wd for wd in reversed(w_list) if wd["start"] <= t <= (wd["end"] + 0.04)), None)
            pad_x, pad_y = 22.0, 10.0
            toks = []
            tot_w = 0.0
            for wd in w_list:
                txt = _clean_doc_text(wd["word"]).upper()
                if not txt:
                    continue
                is_act = wd is active_wd
                sc = 1.10 if is_act else 1.0
                tw = float(cap_font.measureText(txt))
                sw = (tw + pad_x * 2.0) * sc if is_act else tw
                toks.append({"txt": txt, "w": tw, "sw": sw, "act": is_act, "sc": sc, "pidx": int(wd.get("g_idx", 0))})
                tot_w += sw
            if toks:
                tot_w += space_w * (len(toks) - 1)
                max_line_w = w * 0.84
                lscale = min(1.0, max_line_w / max(1.0, tot_w))
                cap_y = h * (0.90 if is_wide else 0.84)
                canvas.save()
                canvas.translate(w * 0.5, cap_y)
                canvas.scale(lscale, lscale)
                cx_pos = -tot_w * 0.5
                pos_map = {}
                for tk in toks:
                    pos_map[id(tk)] = cx_pos + tk["sw"] * 0.5
                    cx_pos += tk["sw"] + space_w
                for tk in [x for x in toks if not x["act"]] + [x for x in toks if x["act"]]:
                    canvas.save()
                    canvas.translate(pos_map[id(tk)], 0.0)
                    if tk["act"]:
                        canvas.scale(tk["sc"], tk["sc"])
                        pbg, ptx, (gr, gg, gb, ga) = ACTIVE_PILL_PALETTE[tk["pidx"] % len(ACTIVE_PILL_PALETTE)]
                        pr = skia.Rect.MakeXYWH(-tk["w"] * 0.5 - pad_x, -ascent - pad_y, tk["w"] + pad_x * 2.0, ascent + descent + pad_y * 2.0)
                        pp = skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg))
                        pp.setImageFilter(skia.ImageFilters.DropShadow(0, 6, 16, 16, skia.ColorSetARGB(ga, gr, gg, gb)))
                        canvas.drawRoundRect(pr, 18, 18, pp)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                    else:
                        stp = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=10.0, StrokeJoin=skia.Paint.kRound_Join, Color=skia.ColorSetARGB(255, 8, 5, 14))
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, stp)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                    canvas.restore()
                canvas.restore()
            break


# ---------------------------------------------------------------------------
# 6. Scene-by-Scene Documentary Render Engine (Flat RAM + Thermal Guard + LUT 02_dark_wealth.cube)
# ---------------------------------------------------------------------------
def _render_single_doc_scene_to_disk(
    scene: NetflixDocScene,
    s_idx: int,
    scene_dur: float,
    chapter_intro_s: float,
    scene_words: List[Dict[str, Any]],
    global_t_offset: float,
    total_est_dur: float,
    out_scene_mp4: Path,
    w: int,
    h: int,
    fps: int,
    lut_path: Path,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    caption_tf: skia.Typeface,
    thermal_limit_c: float,
) -> Path:
    """Render one documentary scene at 30fps in C++ Skia directly to disk with LUT 02_dark_wealth.cube & 35mm grain."""
    try:
        os.nice(10)
    except OSError:
        pass
    thermal_guard_wait(limit_c=thermal_limit_c)

    surface = skia.Surface(w, h)
    chunks = group_words_into_chunks(scene_words, max_words=3)
    total_frames = max(1, int(math.ceil(scene_dur * fps)))

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    vf_parts = []
    if lut_path.exists():
        # Subtle 38% LUT blend preserves crisp legibility of Gold/Lime/Pink UI overlays while imparting Dark Wealth cinema grade
        vf_parts.append(
            f"split[orig][lut_in];[lut_in]lut3d=file='{lut_path.as_posix()}':interp=trilinear[lut_out];"
            f"[orig][lut_out]blend=all_mode=normal:all_opacity=0.32"
        )
    # Subtle 35mm cinema film grain
    vf_parts.append("noise=alls=4:allf=t+u")
    vf_parts.append(hw_suffix)
    vf_chain = ",".join(vf_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *pre_args,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-vf",
        vf_chain,
        "-t",
        f"{scene_dur:.3f}",
        *enc_args,
        "-an",
        str(out_scene_mp4),
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=get_vaapi_env(),
        preexec_fn=nice_preexec,
    )
    assert proc.stdin is not None

    mode_drawers = {
        "parallax_25d_photo": _draw_mode_parallax_25d_photo,
        "newspaper_highlighter": _draw_mode_newspaper_highlighter,
        "dark_map_route": _draw_mode_dark_map_route,
        "sliding_timeline": _draw_mode_sliding_timeline,
        "red_string_board": _draw_mode_red_string_board,
    }
    drawer = mode_drawers.get(scene.visual_mode, _draw_mode_parallax_25d_photo)

    try:
        for fi in range(total_frames):
            local_t = fi / float(fps)
            global_t = global_t_offset + local_t
            c = surface.getCanvas()

            if chapter_intro_s > 0.0 and local_t < chapter_intro_s:
                _draw_obsidian_cinema_backdrop(c, w, h, global_t)
                _draw_chapter_card_overlay(
                    c,
                    w,
                    h,
                    scene.chapter_card or _spaced_chapter_label("I"),
                    scene.chapter_subtitle or "",
                    local_t,
                    chapter_intro_s,
                    title_tf,
                    ui_tf,
                )
            else:
                body_t = max(0.0, local_t - chapter_intro_s)
                body_dur = max(0.5, scene_dur - chapter_intro_s)
                prog = min(1.0, body_t / body_dur)
                drawer(c, w, h, scene, prog, global_t, title_tf, ui_tf)
                _draw_sleek_lower_third(c, w, h, scene, body_t, body_dur, title_tf, ui_tf)
                _draw_doc_subtitles(c, w, h, chunks, local_t, caption_tf)

            # Top slim cinema progress bar
            bar_w = max(8.0, w * min(1.0, global_t / max(0.1, total_est_dur)))
            bar_p = skia.Paint(AntiAlias=True)
            bar_p.setShader(
                skia.GradientShader.MakeLinear(
                    [(0, 0), (w, 0)],
                    [hex_to_skia("#FFD166"), hex_to_skia("#FF2E93"), hex_to_skia("#B8FF01")],
                )
            )
            c.drawRoundRect(skia.Rect.MakeXYWH(0, 0, bar_w, 8), 4, 4, bar_p)

            proc.stdin.write(surface.makeImageSnapshot().tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    stderr = proc.stderr.read() if proc.stderr else b""
    proc.wait(timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"NetflixDoc scene #{s_idx + 1} encode failed: {stderr.decode(errors='ignore')}")
    return out_scene_mp4


async def render_netflix_documentary(
    plan: Union[Dict[str, Any], NetflixDocPlan],
    work_dir: Path,
    out_master_mp4: Path,
    music_mp3: Optional[Path] = None,
    fps: int = 30,
    thermal_limit_c: float = 85.0,
    progress_cb=None,
) -> Dict[str, Any]:
    """Render a complete Netflix / MagnatesMedia investigative documentary scene-by-scene to disk
    with C++ Skia investigative visual modes, Chapter Cards + sub_boom.wav hits, LUT 02_dark_wealth.cube,
    35mm film grain, and -14 LUFS broadcast audio mastering.
    """
    fps = 30 if int(fps) <= 30 else 60
    work_dir.mkdir(parents=True, exist_ok=True)
    out_master_mp4.parent.mkdir(parents=True, exist_ok=True)

    plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else dict(plan)
    plan_obj = NetflixDocPlan.model_validate(plan_dict)

    w, h = (1920, 1080) if plan_obj.aspect_ratio == "16:9" else (1080, 1920)
    lut_path = ASSETS_DIR / "luts" / (plan_obj.lut_file or "02_dark_wealth.cube")
    sfx_dir = ASSETS_DIR / "sfx"
    if music_mp3 is None or not Path(music_mp3).exists():
        music_mp3 = ASSETS_DIR / "music" / "dark_pulse.mp3"

    title_tf, font_info = _load_verified_typeface("Montserrat-Black.ttf", role="doc_title")
    ui_tf, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="doc_ui")
    caption_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="doc_caption")

    # 1. Synthesize narration per scene & compute exact timeline with Chapter Card intro windows
    scene_records: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    audio_parts: List[Path] = []
    sfx_events: List[Tuple[Path, float, float]] = []

    cursor_t = 0.0
    pause_gap_s = 0.24
    gap_wav = work_dir / "_doc_gap.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{pause_gap_s:.2f}", str(gap_wav)],
        thermal_limit_c=thermal_limit_c,
    )

    n_scenes = len(plan_obj.scenes)
    for s_idx, sc in enumerate(plan_obj.scenes):
        if progress_cb:
            pct = 12 + int(28 * ((s_idx + 1) / float(max(1, n_scenes))))
            progress_cb(pct, f"Sintetizando narração investigativa cena {s_idx + 1}/{n_scenes} ({sc.visual_mode})...")

        chapter_intro_s = 1.65 if sc.chapter_card else 0.0
        chap_gap_wav = work_dir / f"_chap_intro_{s_idx:03d}.wav"
        if chapter_intro_s > 0.0:
            run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{chapter_intro_s:.2f}",
                    str(chap_gap_wav),
                ],
                thermal_limit_c=thermal_limit_c,
            )
            audio_parts.append(chap_gap_wav)
            # Mandatory sub_boom.wav hit on Chapter Card reveal
            sfx_events.append((sfx_dir / "sub_boom.wav", cursor_t + 0.04, 0.42))

        wav_p, words, speech_dur = await _synthesize_doc_scene_narration(
            sc.narration,
            plan_obj.voice_id,
            plan_obj.lang,
            work_dir,
            f"doc_narr_{s_idx:03d}",
            thermal_limit_c=thermal_limit_c,
        )

        # Shift scene words by chapter_intro_s (local scene time) and cursor_t (master time)
        local_words: List[Dict[str, Any]] = []
        for wd in words:
            lw = {
                "word": wd["word"],
                "start": round(chapter_intro_s + float(wd["start"]), 3),
                "end": round(chapter_intro_s + float(wd["end"]), 3),
            }
            local_words.append(lw)
            all_words.append(
                {
                    "word": wd["word"],
                    "start": round(cursor_t + lw["start"], 3),
                    "end": round(cursor_t + lw["end"], 3),
                }
            )

        # Mode-specific subtle investigative sound design
        body_start_t = cursor_t + chapter_intro_s
        if s_idx == 0:
            sfx_events.append((sfx_dir / "cinematic_hit.wav", 0.05, 0.36))
        if sc.visual_mode == "parallax_25d_photo":
            sfx_events.append((sfx_dir / "camera_shutter.wav", body_start_t + 0.12, 0.28))
        elif sc.visual_mode == "newspaper_highlighter":
            sfx_events.append((sfx_dir / "whoosh_deep.wav", body_start_t + 0.10, 0.30))
        elif sc.visual_mode == "dark_map_route":
            sfx_events.append((sfx_dir / "ui_click.wav", body_start_t + 0.15, 0.26))
        elif sc.visual_mode == "sliding_timeline":
            sfx_events.append((sfx_dir / "cash_chime.wav", body_start_t + 0.18, 0.28))
        elif sc.visual_mode == "red_string_board":
            sfx_events.append((sfx_dir / "heartbeat.wav", body_start_t + 0.10, 0.28))

        scene_dur = round(chapter_intro_s + speech_dur + pause_gap_s, 3)
        scene_records.append(
            {
                "s_idx": s_idx,
                "scene": sc,
                "start_t": cursor_t,
                "scene_dur": scene_dur,
                "chapter_intro_s": chapter_intro_s,
                "local_words": local_words,
            }
        )
        audio_parts.append(wav_p)
        audio_parts.append(gap_wav)
        cursor_t = round(cursor_t + scene_dur, 3)

    # Concatenate full narration WAV and master Broadcast Audio (-14 LUFS + 0.40s clean tail)
    concat_audio_txt = work_dir / "doc_audio_concat.txt"
    concat_audio_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in audio_parts), encoding="utf-8")
    raw_full_wav = work_dir / "doc_narration_full.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_audio_txt), "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_full_wav)],
        thermal_limit_c=thermal_limit_c,
    )

    master_audio = work_dir / "doc_master_audio.m4a"
    master_audio, final_dur = await asyncio.to_thread(
        master_broadcast_audio,
        raw_full_wav,
        music_mp3,
        sfx_events,
        master_audio,
        cursor_t,
        0.17,
        0.40,
        thermal_limit_c=thermal_limit_c,
    )

    # Extend last scene duration by the 0.40s broadcast audio tail so video & audio end together
    if scene_records:
        tail_delta = max(0.0, round(final_dur - cursor_t, 3))
        scene_records[-1]["scene_dur"] = round(scene_records[-1]["scene_dur"] + tail_delta, 3)

    # 2. Render each scene to disk one-by-one (os.nice(10) + thermal_guard_wait -> flat RAM!)
    scene_mp4_paths: List[Path] = []
    for rec in scene_records:
        s_idx = rec["s_idx"]
        sc: NetflixDocScene = rec["scene"]
        if progress_cb:
            pct = 45 + int(42 * ((s_idx + 1) / float(max(1, n_scenes))))
            progress_cb(
                pct,
                f"Renderizando cena Skia C++ {s_idx + 1}/{n_scenes} [{sc.visual_mode}] ({w}x{h} @ {fps}fps | LUT 02_dark_wealth)...",
            )
        out_sc_mp4 = work_dir / f"doc_scene_{s_idx:03d}.mp4"
        await asyncio.to_thread(
            _render_single_doc_scene_to_disk,
            sc,
            s_idx,
            rec["scene_dur"],
            rec["chapter_intro_s"],
            rec["local_words"],
            rec["start_t"],
            final_dur,
            out_sc_mp4,
            w,
            h,
            fps,
            lut_path,
            title_tf,
            ui_tf,
            caption_tf,
            thermal_limit_c,
        )
        scene_mp4_paths.append(out_sc_mp4)

    # 3. Concatenate rendered scene MP4s with zero-reencode stream copy + mux master broadcast audio
    video_concat_txt = work_dir / "doc_video_concat.txt"
    video_concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in scene_mp4_paths), encoding="utf-8")
    base_scenes_mp4 = work_dir / "base_scenes.mp4"
    run_ffmpeg_safe(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(video_concat_txt),
            "-c:v", "copy", "-an",
            str(base_scenes_mp4),
        ],
        thermal_limit_c=thermal_limit_c,
    )

    run_ffmpeg_safe(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(base_scenes_mp4),
            "-i", str(master_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart",
            str(out_master_mp4),
        ],
        thermal_limit_c=thermal_limit_c,
    )

    chapters_used = [sc.chapter_card for sc in plan_obj.scenes if sc.chapter_card]
    modes_used = [sc.visual_mode for sc in plan_obj.scenes]

    return {
        "master_mp4": str(out_master_mp4),
        "master_audio": str(master_audio),
        "base_scenes_mp4": str(base_scenes_mp4),
        "words": all_words,
        "duration_s": round(_get_wav_duration(out_master_mp4), 2),
        "aspect_ratio": plan_obj.aspect_ratio,
        "width": w,
        "height": h,
        "fps": fps,
        "lang": plan_obj.lang,
        "channel_name": plan_obj.channel_name,
        "voice_id": plan_obj.voice_id,
        "lut_file": plan_obj.lut_file,
        "film_grain": "35mm_active",
        "doc_engine": "netflix_magnates_cinema_v1",
        "font_verified": font_info,
        "title": plan_obj.title,
        "subtitle": plan_obj.subtitle,
        "thumbnail_hook": plan_obj.thumbnail_hook,
        "scenes_count": len(plan_obj.scenes),
        "chapters": chapters_used,
        "visual_modes_used": modes_used,
    }
