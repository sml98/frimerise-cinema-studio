"""FrimeRise Twin High-RPM Documentary Channels & 10-Episode Ready Queue Seeder.
Registers:
  1. Canal BR: "Dossiê Capital" (16:9 Documentário Cinema, LUT 02_dark_wealth.cube, pt-BR-AntonioNeural, Cascata de 5 Shorts ativa, lang="pt_br")
  2. Canal US: "Vault Files" (16:9 Documentário Cinema, LUT 02_dark_wealth.cube, en-US-AndrewMultilingualNeural, Cascata de 5 Shorts ativa, lang="en_us")
  3. Ready Queue of 10 Investigative Documentaries in data/twin_channels_queue.json with exact 3-word PT-BR & EN-US thumbnail hooks.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from database import get_conn, init_db, list_clients

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
QUEUE_JSON_PATH = DATA_DIR / "twin_channels_queue.json"


TWIN_CHANNELS_SPEC: List[Dict[str, Any]] = [
    {
        "channel_key": "dossie_capital_br",
        "name": "Dossiê Capital",
        "lang": "pt_br",
        "country": "BR",
        "currency": "BRL / USD",
        "format": "16:9 Documentário Cinema",
        "engine_style": "netflix_doc",
        "aspect_ratio": "16:9",
        "niche": "16:9 Documentário Cinema • Finanças, Fraudes & Impérios (Alto RPM)",
        "preset_id": "magnates_doc",
        "lut_file": "02_dark_wealth.cube",
        "voice_engine": "edge",
        "voice_id": "pt-BR-AntonioNeural",
        "voice_blend": {"pf_dora": 0.0, "pm_alex": 0.70, "pm_santa": 0.30},
        "logo_path": "assets/brand/frimerise_logo.png",
        "watermark_text": "DOSSIÊ CAPITAL • FRIMERISE",
        "shorts_cascade_active": True,
        "shorts_cascade_count": 5,
    },
    {
        "channel_key": "vault_files_us",
        "name": "Vault Files",
        "lang": "en_us",
        "country": "US",
        "currency": "USD ($25-$45 RPM)",
        "format": "16:9 Documentário Cinema",
        "engine_style": "netflix_doc",
        "aspect_ratio": "16:9",
        "niche": "16:9 Documentário Cinema • High-RPM US Financial Mysteries (USD)",
        "preset_id": "magnates_doc",
        "lut_file": "02_dark_wealth.cube",
        "voice_engine": "edge",
        "voice_id": "en-US-AndrewMultilingualNeural",
        "voice_blend": {"pf_dora": 0.0, "pm_alex": 0.75, "pm_santa": 0.25},
        "logo_path": "assets/brand/frimerise_logo.png",
        "watermark_text": "VAULT FILES • FRIMERISE",
        "shorts_cascade_active": True,
        "shorts_cascade_count": 5,
    },
]


TEN_DOCUMENTARY_EPISODES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "slug": "nick_leeson_barings_bank",
        "short_name": "Nick Leeson / Barings Bank",
        "title_pt": "Como um Único Operador Quebrou o Banco Mais Antigo da Rainha (Nick Leeson / Barings Bank)",
        "title_en": "How One Rogue Trader Bankrupted the Queen's Oldest Bank (Nick Leeson / Barings Bank)",
        "thumb_hook_pt": "ESCONDEU $1.4 BILHÃO",
        "thumb_hook_en": "HID $1.4 BILLION",
        "category": "Colapso Bancário",
        "visual_modes": ["newspaper_highlighter", "sliding_timeline", "red_string_board", "dark_map_route", "parallax_25d_photo"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 2,
        "slug": "monopolio_luxottica",
        "short_name": "Monopólio Luxottica",
        "title_pt": "A Ilusão dos Óculos de Luxo: Como Uma Única Empresa Controla 80% das Marcas (Monopólio Luxottica)",
        "title_en": "The Eyewear Illusion: How One Secret Giant Owns Every Luxury Brand (Luxottica Monopoly)",
        "thumb_hook_pt": "TUDO É DELES",
        "thumb_hook_en": "THEY OWN ALL",
        "category": "Monopólio Oculto",
        "visual_modes": ["red_string_board", "newspaper_highlighter", "sliding_timeline", "parallax_25d_photo", "dark_map_route"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 3,
        "slug": "fraude_theranos",
        "short_name": "Fraude Theranos",
        "title_pt": "A Mentira de US$ 9 Bilhões no Vale do Silício: O Sangue Falso da Theranos",
        "title_en": "Silicon Valley's $9 Billion Lie: Inside the Theranos Blood-Testing Mirage",
        "thumb_hook_pt": "CAIXA VAZIA",
        "thumb_hook_en": "IT WAS EMPTY",
        "category": "Fraude Bilionária",
        "visual_modes": ["parallax_25d_photo", "newspaper_highlighter", "red_string_board", "sliding_timeline", "dark_map_route"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 4,
        "slug": "evaldas_rimasauskas_google_fb",
        "short_name": "Evaldas Rimasauskas Boletos Google/FB",
        "title_pt": "O Homem que Enviou Boletos Falsos para o Google e o Facebook — E Eles Pagaram US$ 122 Milhões",
        "title_en": "The Man Who Sent Fake Invoices to Google and Facebook — And They Paid $122 Million",
        "thumb_hook_pt": "ELES PAGARAM TUDO",
        "thumb_hook_en": "THEY JUST PAID",
        "category": "Golpe Audacioso",
        "visual_modes": ["dark_map_route", "newspaper_highlighter", "red_string_board", "sliding_timeline", "parallax_25d_photo"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 5,
        "slug": "colapso_camarao_infinito_red_lobster",
        "short_name": "Colapso Camarão Infinito Red Lobster",
        "title_pt": "A Promoção de US$ 20 que Destruiu uma Rede Bilionária: O Colapso do Camarão Infinito da Red Lobster",
        "title_en": "The $20 Promotion That Crushed a Restaurant Empire: Red Lobster's Endless Shrimp Collapse",
        "thumb_hook_pt": "PREJUÍZO INFINITO",
        "thumb_hook_en": "INFINITE LOSS",
        "category": "Desastre Corporativo",
        "visual_modes": ["sliding_timeline", "newspaper_highlighter", "parallax_25d_photo", "red_string_board", "dark_map_route"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 6,
        "slug": "guerra_irmaos_adidas_vs_puma",
        "short_name": "Guerra Irmãos Adidas vs Puma",
        "title_pt": "A Cidade Dividida pelo Ódio: A Guerra Secreta dos Irmãos que Criaram a Adidas e a Puma",
        "title_en": "The Town Divided by Hatred: The Blood Feud Behind Adidas and Puma",
        "thumb_hook_pt": "IRMÃOS INIMIGOS",
        "thumb_hook_en": "BLOOD RIVALS",
        "category": "Rivalidade Histórica",
        "visual_modes": ["parallax_25d_photo", "dark_map_route", "sliding_timeline", "newspaper_highlighter", "red_string_board"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 7,
        "slug": "caca_militar_da_pepsi",
        "short_name": "Caça Militar da Pepsi",
        "title_pt": "O Universitário que Exigiu um Caça Militar Harrier de US$ 33 Milhões da Pepsi",
        "title_en": "The College Student Who Demanded a $33 Million Harrier Fighter Jet From Pepsi",
        "thumb_hook_pt": "ELE JUNTOU OS PONTOS",
        "thumb_hook_en": "HE BOUGHT IT",
        "category": "Batalha Judicial",
        "visual_modes": ["newspaper_highlighter", "sliding_timeline", "parallax_25d_photo", "red_string_board", "dark_map_route"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 8,
        "slug": "us_2b_fantasmas_wirecard",
        "short_name": "US$ 2B Fantasmas Wirecard",
        "title_pt": "Os US$ 2 Bilhões que Nunca Existiram: O Maior Escândalo Financeiro da Alemanha (Wirecard)",
        "title_en": "The $2 Billion That Never Existed: Inside Germany's Wirecard Financial Scandal",
        "thumb_hook_pt": "DINHEIRO FANTASMA",
        "thumb_hook_en": "GHOST BILLIONS",
        "category": "Contabilidade Fantasma",
        "visual_modes": ["red_string_board", "dark_map_route", "newspaper_highlighter", "sliding_timeline", "parallax_25d_photo"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 9,
        "slug": "forest_city_100b_vazia",
        "short_name": "Forest City US$ 100B Vazia",
        "title_pt": "A Metrópole Futurista de US$ 100 Bilhões Construída no Mar — Que Hoje Está 98% Vazia (Forest City)",
        "title_en": "The $100 Billion Futuristic Mega-City Built in the Ocean — Now 98% Empty (Forest City)",
        "thumb_hook_pt": "98% VAZIA",
        "thumb_hook_en": "98% EMPTY",
        "category": "Megaprojeto Fantasma",
        "visual_modes": ["dark_map_route", "parallax_25d_photo", "sliding_timeline", "newspaper_highlighter", "red_string_board"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
    {
        "id": 10,
        "slug": "engenheiro_12150_pudins",
        "short_name": "Engenheiro dos 12.150 Pudins",
        "title_pt": "O Engenheiro que Comprou 12.150 Pudins de Chocolate e Ganhou Milhas Aéreas Infinitas",
        "title_en": "The Engineer Who Bought 12,150 Chocolate Puddings for Unlimited Frequent Flyer Miles",
        "thumb_hook_pt": "BRECHA GENIAL",
        "thumb_hook_en": "THE PUDDING GLITCH",
        "category": "Arbitragem Genial",
        "visual_modes": ["sliding_timeline", "newspaper_highlighter", "red_string_board", "parallax_25d_photo", "dark_map_route"],
        "target_minutes": 0.5,
        "shorts_cascade_count": 5,
    },
]


def seed_twin_channels_and_queue() -> Dict[str, Any]:
    """Idempotently register 'Dossiê Capital' (BR) and 'Vault Files' (US) in SQLite clients table
    and persist the 10-episode Ready Queue in data/twin_channels_queue.json.
    """
    init_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")

    registered_channels: Dict[str, Dict[str, Any]] = {}
    with get_conn() as conn:
        for ch in TWIN_CHANNELS_SPEC:
            existing = conn.execute(
                "SELECT id FROM clients WHERE name = ? ORDER BY id ASC LIMIT 1",
                (ch["name"],),
            ).fetchone()
            blend_json = json.dumps(ch["voice_blend"])
            if existing:
                cid = int(existing["id"])
                conn.execute(
                    """
                    UPDATE clients SET
                        niche=?, preset_id=?, lut_file=?, voice_engine=?, voice_id=?,
                        voice_blend=?, logo_path=?, watermark_text=?
                    WHERE id=?
                    """,
                    (
                        ch["niche"],
                        ch["preset_id"],
                        ch["lut_file"],
                        ch["voice_engine"],
                        ch["voice_id"],
                        blend_json,
                        ch["logo_path"],
                        ch["watermark_text"],
                        cid,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO clients (
                        name, niche, preset_id, lut_file, voice_engine, voice_id,
                        voice_blend, logo_path, proxy_url, watermark_text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                    """,
                    (
                        ch["name"],
                        ch["niche"],
                        ch["preset_id"],
                        ch["lut_file"],
                        ch["voice_engine"],
                        ch["voice_id"],
                        blend_json,
                        ch["logo_path"],
                        ch["watermark_text"],
                        now,
                    ),
                )
                cid = int(cur.lastrowid)

            registered_channels[ch["lang"]] = {
                **ch,
                "client_id": cid,
            }

    payload = {
        "updated_at": now,
        "channels": {
            "pt_br": registered_channels["pt_br"],
            "en_us": registered_channels["en_us"],
        },
        "episodes": TEN_DOCUMENTARY_EPISODES,
    }
    QUEUE_JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def get_twin_channels_queue() -> Dict[str, Any]:
    """Load or seed the Twin Channels + 10 Documentary Episodes Ready Queue."""
    if not QUEUE_JSON_PATH.exists():
        return seed_twin_channels_and_queue()
    try:
        data = json.loads(QUEUE_JSON_PATH.read_text(encoding="utf-8"))
        # Ensure clients exist in DB and client_ids are current
        clients = {c["name"]: c["id"] for c in list_clients()}
        if "Dossiê Capital" not in clients or "Vault Files" not in clients:
            return seed_twin_channels_and_queue()
        data["channels"]["pt_br"]["client_id"] = clients["Dossiê Capital"]
        data["channels"]["en_us"]["client_id"] = clients["Vault Files"]
        return data
    except Exception:
        return seed_twin_channels_and_queue()


def get_doc_episode(episode_id: int) -> Optional[Dict[str, Any]]:
    """Lookup one of the 10 pre-seeded documentary episodes by ID (1..10)."""
    q = get_twin_channels_queue()
    for ep in q.get("episodes", []):
        if int(ep.get("id", 0)) == int(episode_id):
            return ep
    return None


if __name__ == "__main__":
    res = seed_twin_channels_and_queue()
    br = res["channels"]["pt_br"]
    us = res["channels"]["en_us"]
    print(f"[FrimeRise Seeder] Canais Gêmeos registrados com sucesso:")
    print(f"  🇧🇷 Canal BR (#{br['client_id']}): {br['name']} | {br['format']} | LUT={br['lut_file']} | Voz={br['voice_id']} | Shorts={br['shorts_cascade_count']}")
    print(f"  🇺🇸 Canal US (#{us['client_id']}): {us['name']} | {us['format']} | LUT={us['lut_file']} | Voz={us['voice_id']} | Shorts={us['shorts_cascade_count']}")
    print(f"[FrimeRise Seeder] {len(res['episodes'])} Episódios Documentais prontos em {QUEUE_JSON_PATH}:")
    for ep in res["episodes"]:
        print(f"  #{ep['id']:02d} {ep['short_name']} -> BR: [{ep['thumb_hook_pt']}] | US: [{ep['thumb_hook_en']}]")
