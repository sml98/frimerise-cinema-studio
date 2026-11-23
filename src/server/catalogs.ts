export interface PresetRecord {
  id: string;
  name: string;
  tagline: string;
  is_default: number;
  lut_file: string;
  font_file: string;
  music_file: string;
  primary_color: string;
  secondary_color: string;
  highlight_color: string;
  accent_gold: string;
  bg_box_color: string;
  text_color: string;
  stroke_color: string;
  caption_style: string;
  voice_engine: string;
  voice_id: string;
  voice_blend: string;
  motion_cards: number;
  sfx_intensity: string;
}

export interface VoiceOption {
  id: string;
  name: string;
  lang?: string;
}

export interface TwinChannelSpec {
  channel_key: string;
  name: string;
  lang: 'pt_br' | 'en_us';
  country: string;
  currency: string;
  format: string;
  engine_style: string;
  aspect_ratio: string;
  niche: string;
  preset_id: string;
  lut_file: string;
  voice_engine: string;
  voice_id: string;
  voice_blend: Record<string, number>;
  logo_path: string;
  watermark_text: string;
  shorts_cascade_active: boolean;
  shorts_cascade_count: number;
  client_id?: number;
}

export interface DocEpisode {
  id: number;
  slug: string;
  short_name: string;
  title_pt: string;
  title_en: string;
  thumb_hook_pt: string;
  thumb_hook_en: string;
  category: string;
  visual_modes: string[];
  target_minutes: number;
  shorts_cascade_count: number;
}

export const DEFAULT_PRESETS: PresetRecord[] = [
  {
    id: 'frimerise_signature',
    name: 'FrimeRise Signature',
    tagline: 'Estética Cyber-Luxury oficial: Verde Lima, Dourado, Rosa Frime e Lilás',
    is_default: 1,
    lut_file: '01_frimerise_signature.cube',
    font_file: 'Montserrat-Black.ttf',
    music_file: 'dark_pulse.mp3',
    primary_color: '#FF2E93',
    secondary_color: '#B388FF',
    highlight_color: '#B8FF01',
    accent_gold: '#FFD166',
    bg_box_color: '#140E24CC',
    text_color: '#FFFFFF',
    stroke_color: '#0B0713',
    caption_style: 'spring_pill_gradient',
    voice_engine: 'edge',
    voice_id: 'pt-BR-AntonioNeural',
    voice_blend: JSON.stringify({ pf_dora: 0.35, pm_alex: 0.65, pm_santa: 0.0 }),
    motion_cards: 1,
    sfx_intensity: 'high',
  },
  {
    id: 'hormozi_rebel',
    name: 'Hormozi Rebel',
    tagline: 'Cortes rápidos, palavras-chave em Verde Lima e Amarelo explosivo + emojis',
    is_default: 0,
    lut_file: '02_dark_wealth.cube',
    font_file: 'Anton-Regular.ttf',
    music_file: 'dark_pulse.mp3',
    primary_color: '#B8FF01',
    secondary_color: '#FFD166',
    highlight_color: '#B8FF01',
    accent_gold: '#FFD166',
    bg_box_color: '#000000B0',
    text_color: '#FFFFFF',
    stroke_color: '#000000',
    caption_style: 'hormozi_bounce',
    voice_engine: 'edge',
    voice_id: 'pt-BR-AntonioNeural',
    voice_blend: JSON.stringify({ pf_dora: 0.0, pm_alex: 0.8, pm_santa: 0.2 }),
    motion_cards: 1,
    sfx_intensity: 'high',
  },
  {
    id: 'magnates_doc',
    name: 'Magnates Doc',
    tagline: 'Mini-documentário cinematográfico com gráficos de barras e LUT Teal & Orange',
    is_default: 0,
    lut_file: '03_teal_orange_cinema.cube',
    font_file: 'BebasNeue-Regular.ttf',
    music_file: 'epic_doc.mp3',
    primary_color: '#FFD166',
    secondary_color: '#38BDF8',
    highlight_color: '#FFD166',
    accent_gold: '#FFD166',
    bg_box_color: '#090D16D9',
    text_color: '#F8FAFC',
    stroke_color: '#020617',
    caption_style: 'cinematic_serif_bar',
    voice_engine: 'edge',
    voice_id: 'pt-BR-FabioNeural',
    voice_blend: JSON.stringify({ pf_dora: 0.0, pm_alex: 0.4, pm_santa: 0.6 }),
    motion_cards: 1,
    sfx_intensity: 'medium',
  },
  {
    id: 'mrbeast_hyper',
    name: 'MrBeast Hyper',
    tagline: 'Energia máxima, contadores numéricos gigantes e transições rápidas',
    is_default: 0,
    lut_file: '04_crisp_commercial.cube',
    font_file: 'Montserrat-Black.ttf',
    music_file: 'corporate_focus.mp3',
    primary_color: '#FF2E93',
    secondary_color: '#B8FF01',
    highlight_color: '#FFD166',
    accent_gold: '#FFD166',
    bg_box_color: '#FF2E93DD',
    text_color: '#FFFFFF',
    stroke_color: '#0B0713',
    caption_style: 'hyper_pop',
    voice_engine: 'edge',
    voice_id: 'pt-BR-JulioNeural',
    voice_blend: JSON.stringify({ pf_dora: 0.2, pm_alex: 0.8, pm_santa: 0.0 }),
    motion_cards: 1,
    sfx_intensity: 'high',
  },
  {
    id: 'luxury_minimalist',
    name: 'Luxury Minimalist',
    tagline: 'Sofisticação clean com dourado metálico, ritmo cadenciado e tipografia elegante',
    is_default: 0,
    lut_file: '02_dark_wealth.cube',
    font_file: 'PlusJakartaSans-ExtraBold.ttf',
    music_file: 'lo_fi_study.mp3',
    primary_color: '#FFD166',
    secondary_color: '#B388FF',
    highlight_color: '#FFD166',
    accent_gold: '#FFD166',
    bg_box_color: '#0B0713B8',
    text_color: '#F5F3FF',
    stroke_color: '#0B0713',
    caption_style: 'minimal_gold',
    voice_engine: 'edge',
    voice_id: 'pt-BR-FranciscaNeural',
    voice_blend: JSON.stringify({ pf_dora: 0.85, pm_alex: 0.15, pm_santa: 0.0 }),
    motion_cards: 1,
    sfx_intensity: 'low',
  },
  {
    id: 'local_business_ugc',
    name: 'Local Business Ads (UGC)',
    tagline: 'Anúncios comerciais de alta conversão para clínicas, lojas, imóveis e delivery',
    is_default: 0,
    lut_file: '04_crisp_commercial.cube',
    font_file: 'PlusJakartaSans-ExtraBold.ttf',
    music_file: 'corporate_focus.mp3',
    primary_color: '#FF2E93',
    secondary_color: '#B8FF01',
    highlight_color: '#B8FF01',
    accent_gold: '#FFD166',
    bg_box_color: '#140E24E6',
    text_color: '#FFFFFF',
    stroke_color: '#0B0713',
    caption_style: 'commercial_highlight',
    voice_engine: 'edge',
    voice_id: 'pt-BR-ThalitaNeural',
    voice_blend: JSON.stringify({ pf_dora: 1.0, pm_alex: 0.0, pm_santa: 0.0 }),
    motion_cards: 1,
    sfx_intensity: 'medium',
  },
  {
    id: 'dark_mystery',
    name: 'Dark Mystery',
    tagline: 'Suspense hipnótico, psicologia sombria e curiosidades com brilho Lilás/Neon',
    is_default: 0,
    lut_file: '05_cyber_neon.cube',
    font_file: 'Montserrat-ExtraBold.ttf',
    music_file: 'dark_pulse.mp3',
    primary_color: '#B388FF',
    secondary_color: '#FF2E93',
    highlight_color: '#B388FF',
    accent_gold: '#FFD166',
    bg_box_color: '#0B0713E6',
    text_color: '#EDE9FE',
    stroke_color: '#05020A',
    caption_style: 'neon_glow',
    voice_engine: 'edge',
    voice_id: 'pt-BR-NicolauNeural',
    voice_blend: JSON.stringify({ pf_dora: 0.0, pm_alex: 0.3, pm_santa: 0.7 }),
    motion_cards: 1,
    sfx_intensity: 'high',
  },
];

export const TWIN_CHANNELS_SPEC: TwinChannelSpec[] = [
  {
    channel_key: 'dossie_capital_br',
    name: 'Dossiê Capital',
    lang: 'pt_br',
    country: 'BR',
    currency: 'BRL / USD',
    format: '16:9 Documentário Cinema',
    engine_style: 'netflix_doc',
    aspect_ratio: '16:9',
    niche: '16:9 Documentário Cinema • Finanças, Fraudes & Impérios (Alto RPM)',
    preset_id: 'magnates_doc',
    lut_file: '02_dark_wealth.cube',
    voice_engine: 'edge',
    voice_id: 'pt-BR-AntonioNeural',
    voice_blend: { pf_dora: 0.0, pm_alex: 0.7, pm_santa: 0.3 },
    logo_path: 'assets/brand/frimerise_logo.png',
    watermark_text: 'DOSSIÊ CAPITAL • FRIMERISE',
    shorts_cascade_active: true,
    shorts_cascade_count: 5,
  },
  {
    channel_key: 'vault_files_us',
    name: 'Vault Files',
    lang: 'en_us',
    country: 'US',
    currency: 'USD ($25-$45 RPM)',
    format: '16:9 Documentário Cinema',
    engine_style: 'netflix_doc',
    aspect_ratio: '16:9',
    niche: '16:9 Documentário Cinema • High-RPM US Financial Mysteries (USD)',
    preset_id: 'magnates_doc',
    lut_file: '02_dark_wealth.cube',
    voice_engine: 'edge',
    voice_id: 'en-US-AndrewMultilingualNeural',
    voice_blend: { pf_dora: 0.0, pm_alex: 0.75, pm_santa: 0.25 },
    logo_path: 'assets/brand/frimerise_logo.png',
    watermark_text: 'VAULT FILES • FRIMERISE',
    shorts_cascade_active: true,
    shorts_cascade_count: 5,
  },
];

export const TEN_DOCUMENTARY_EPISODES: DocEpisode[] = [
  {
    id: 1,
    slug: 'nick_leeson_barings_bank',
    short_name: 'Nick Leeson / Barings Bank',
    title_pt: 'Como um Único Operador Quebrou o Banco Mais Antigo da Rainha (Nick Leeson / Barings Bank)',
    title_en: "How One Rogue Trader Bankrupted the Queen's Oldest Bank (Nick Leeson / Barings Bank)",
    thumb_hook_pt: 'ESCONDEU $1.4 BILHÃO',
    thumb_hook_en: 'HID $1.4 BILLION',
    category: 'Colapso Bancário',
    visual_modes: ['newspaper_highlighter', 'sliding_timeline', 'red_string_board', 'dark_map_route', 'parallax_25d_photo'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 2,
    slug: 'monopolio_luxottica',
    short_name: 'Monopólio Luxottica',
    title_pt: 'A Ilusão dos Óculos de Luxo: Como Uma Única Empresa Controla 80% das Marcas (Monopólio Luxottica)',
    title_en: 'The Eyewear Illusion: How One Secret Giant Owns Every Luxury Brand (Luxottica Monopoly)',
    thumb_hook_pt: 'TUDO É DELES',
    thumb_hook_en: 'THEY OWN ALL',
    category: 'Monopólio Oculto',
    visual_modes: ['red_string_board', 'newspaper_highlighter', 'sliding_timeline', 'parallax_25d_photo', 'dark_map_route'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 3,
    slug: 'fraude_theranos',
    short_name: 'Fraude Theranos',
    title_pt: 'A Mentira de US$ 9 Bilhões no Vale do Silício: O Sangue Falso da Theranos',
    title_en: "Silicon Valley's $9 Billion Lie: Inside the Theranos Blood-Testing Mirage",
    thumb_hook_pt: 'CAIXA VAZIA',
    thumb_hook_en: 'IT WAS EMPTY',
    category: 'Fraude Bilionária',
    visual_modes: ['parallax_25d_photo', 'newspaper_highlighter', 'red_string_board', 'sliding_timeline', 'dark_map_route'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 4,
    slug: 'evaldas_rimasauskas_google_fb',
    short_name: 'Evaldas Rimasauskas Boletos Google/FB',
    title_pt: 'O Homem que Enviou Boletos Falsos para o Google e o Facebook — E Eles Pagaram US$ 122 Milhões',
    title_en: 'The Man Who Sent Fake Invoices to Google and Facebook — And They Paid $122 Million',
    thumb_hook_pt: 'ELES PAGARAM TUDO',
    thumb_hook_en: 'THEY JUST PAID',
    category: 'Golpe Audacioso',
    visual_modes: ['dark_map_route', 'newspaper_highlighter', 'red_string_board', 'sliding_timeline', 'parallax_25d_photo'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 5,
    slug: 'colapso_camarao_infinito_red_lobster',
    short_name: 'Colapso Camarão Infinito Red Lobster',
    title_pt: 'A Promoção de US$ 20 que Destruiu uma Rede Bilionária: O Colapso do Camarão Infinito da Red Lobster',
    title_en: "The $20 Promotion That Crushed a Restaurant Empire: Red Lobster's Endless Shrimp Collapse",
    thumb_hook_pt: 'PREJUÍZO INFINITO',
    thumb_hook_en: 'INFINITE LOSS',
    category: 'Desastre Corporativo',
    visual_modes: ['sliding_timeline', 'newspaper_highlighter', 'parallax_25d_photo', 'red_string_board', 'dark_map_route'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 6,
    slug: 'guerra_irmaos_adidas_vs_puma',
    short_name: 'Guerra Irmãos Adidas vs Puma',
    title_pt: 'A Cidade Dividida pelo Ódio: A Guerra Secreta dos Irmãos que Criaram a Adidas e a Puma',
    title_en: 'The Town Divided by Hatred: The Blood Feud Behind Adidas and Puma',
    thumb_hook_pt: 'IRMÃOS INIMIGOS',
    thumb_hook_en: 'BLOOD RIVALS',
    category: 'Rivalidade Histórica',
    visual_modes: ['parallax_25d_photo', 'dark_map_route', 'sliding_timeline', 'newspaper_highlighter', 'red_string_board'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 7,
    slug: 'caca_militar_da_pepsi',
    short_name: 'Caça Militar da Pepsi',
    title_pt: 'O Universitário que Exigiu um Caça Militar Harrier de US$ 33 Milhões da Pepsi',
    title_en: 'The College Student Who Demanded a $33 Million Harrier Fighter Jet From Pepsi',
    thumb_hook_pt: 'ELE JUNTOU OS PONTOS',
    thumb_hook_en: 'HE BOUGHT IT',
    category: 'Batalha Judicial',
    visual_modes: ['newspaper_highlighter', 'sliding_timeline', 'parallax_25d_photo', 'red_string_board', 'dark_map_route'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 8,
    slug: 'us_2b_fantasmas_wirecard',
    short_name: 'US$ 2B Fantasmas Wirecard',
    title_pt: 'Os US$ 2 Bilhões que Nunca Existiram: O Maior Escândalo Financeiro da Alemanha (Wirecard)',
    title_en: "The $2 Billion That Never Existed: Inside Germany's Wirecard Financial Scandal",
    thumb_hook_pt: 'DINHEIRO FANTASMA',
    thumb_hook_en: 'GHOST BILLIONS',
    category: 'Contabilidade Fantasma',
    visual_modes: ['red_string_board', 'dark_map_route', 'newspaper_highlighter', 'sliding_timeline', 'parallax_25d_photo'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 9,
    slug: 'forest_city_100b_vazia',
    short_name: 'Forest City US$ 100B Vazia',
    title_pt: 'A Metrópole Futurista de US$ 100 Bilhões Construída no Mar — Que Hoje Está 98% Vazia (Forest City)',
    title_en: 'The $100 Billion Futuristic Mega-City Built in the Ocean — Now 98% Empty (Forest City)',
    thumb_hook_pt: '98% VAZIA',
    thumb_hook_en: '98% EMPTY',
    category: 'Megaprojeto Fantasma',
    visual_modes: ['dark_map_route', 'parallax_25d_photo', 'sliding_timeline', 'newspaper_highlighter', 'red_string_board'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
  {
    id: 10,
    slug: 'engenheiro_12150_pudins',
    short_name: 'Engenheiro dos 12.150 Pudins',
    title_pt: 'O Engenheiro que Comprou 12.150 Pudins de Chocolate e Ganhou Milhas Aéreas Infinitas',
    title_en: 'The Engineer Who Bought 12,150 Chocolate Puddings for Unlimited Frequent Flyer Miles',
    thumb_hook_pt: 'BRECHA GENIAL',
    thumb_hook_en: 'THE PUDDING GLITCH',
    category: 'Arbitragem Genial',
    visual_modes: ['sliding_timeline', 'newspaper_highlighter', 'red_string_board', 'parallax_25d_photo', 'dark_map_route'],
    target_minutes: 0.5,
    shorts_cascade_count: 5,
  },
];

export const DURATION_PRESETS = [
  { seconds: 15, label: '15s', tag: 'Hook Relâmpago • Reels/Shorts' },
  { seconds: 30, label: '30s', tag: 'Viral Curto • Alta Retenção' },
  { seconds: 60, label: '60s', tag: 'Shorts Completo / TikTok Pro' },
  { seconds: 180, label: '3 min', tag: 'Mini-Doc / Storytelling' },
  { seconds: 480, label: '8 min', tag: 'YouTube Mid-Roll High-RPM' },
  { seconds: 900, label: '15 min', tag: 'Documentário Cinema Completo' },
  { seconds: 1020, label: '17 min', tag: 'Documentário Cinema v3.0.0 (Ideal)' },
  { seconds: 1200, label: '20 min', tag: 'Documentário Especial Estendido' },
];

export const VISUAL_LIBRARIES_CATALOG = [
  {
    id: 'real_broll',
    label: '📹 Filmagens Reais HD',
    desc: 'Filmagens Reais HD: Pixabay + Wikimedia + Archive + yt-dlp',
    default_engines: ['cinematic_broll', 'netflix_doc'],
  },
  {
    id: 'photos_25d',
    label: '🖼️ Fotos Reais + Parallax 2.5D',
    desc: 'Fotos Reais + Parallax 2.5D u2netp + cv2.inpaint',
    default_engines: ['netflix_doc'],
  },
  {
    id: 'video_over_video',
    label: '📺 Vídeo sobre Vídeo (PiP)',
    desc: 'Vídeo sobre Vídeo: Monitor PiP Forense + Split-Screen',
    default_engines: ['netflix_doc'],
  },
  {
    id: 'skia_graphics',
    label: '📊 Gráficos Skia C++',
    desc: 'Gráficos Skia C++: Cards, Jornal, Mapa, Timeline, Red-String',
    default_engines: ['cinematic_broll', 'netflix_doc'],
  },
  {
    id: 'cartoon_2d_layer',
    label: '🎭 Personagens 2D Cartoon',
    desc: 'Personagens 2D Cartoon + Rhubarb 9-Visemas',
    default_engines: ['cartoon_2d'],
  },
  {
    id: 'bespoke_ai',
    label: '✨ Arte IA Inédita',
    desc: 'Arte IA Inédita: Pollinations Flux / Google Flow Pro',
    default_engines: [],
  },
  {
    id: 'cinema_35mm_sfx',
    label: '🎞️ Cinema FX 35mm + SFX',
    desc: 'Efeitos Cinema: Granulação 35mm + Partículas + SFX',
    default_engines: ['cinematic_broll', 'cartoon_2d', 'netflix_doc'],
  },
];

export const CAPTION_STYLES_CATALOG = [
  { id: 'hormozi_neon', label: '⚡ Hormozi Pílula Neon (CapCut Spring Bounce + Tilt)' },
  { id: 'karaoke_glow', label: '🌈 Karaokê Glow (Wipe Gradiente Neon Palavra-a-Palavra)' },
  { id: 'word_slam', label: '💥 Word Slam 3D (Impacto Metálico + Shake Viral)' },
  { id: 'selective_emphasis', label: '🎯 Selective Emphasis (Doc 16:9 Keyword Stamp • Courier Prime 64px)' },
  { id: 'cinema_minimal', label: '🎬 Cinema Minimalista (Netflix Blur-Reveal Dourado)' },
  { id: 'typewriter_highlight', label: '📰 Dossiê Highlighter (Typewriter + Marca-Texto Neon)' },
  { id: 'none', label: '🚫 Sem Legendas' },
];

export const PT_BR_EDGE_VOICES: VoiceOption[] = [
  { id: 'pt-BR-AntonioNeural', name: '🇧🇷 Antonio Neural (PT-BR • Grave / Documentário)' },
  { id: 'pt-BR-FranciscaNeural', name: '🇧🇷 Francisca Neural (PT-BR • Clara / Comercial)' },
  { id: 'pt-BR-ThalitaMultilingualNeural', name: '🇧🇷 Thalita Multilingual (PT-BR • Expressiva)' },
  { id: 'pt-BR-FabioNeural', name: '🇧🇷 Fabio Neural (PT-BR • Investigativo)' },
  { id: 'pt-BR-JulioNeural', name: '🇧🇷 Julio Neural (PT-BR • Dinâmico)' },
  { id: 'pt-BR-NicolauNeural', name: '🇧🇷 Nicolau Neural (PT-BR • Suspense)' },
  { id: 'pt-BR-ThalitaNeural', name: '🇧🇷 Thalita Neural (PT-BR • UGC / Anúncios)' },
];

export const ALL_EDGE_VOICES: VoiceOption[] = [
  ...PT_BR_EDGE_VOICES,
  { id: 'en-US-AndrewMultilingualNeural', name: '🇺🇸 Andrew Multilingual (EN-US • Vault Files Grave)' },
  { id: 'en-US-AvaMultilingualNeural', name: '🇺🇸 Ava Multilingual (EN-US • Expressiva)' },
  { id: 'en-US-GuyNeural', name: '🇺🇸 Guy Neural (EN-US • Narrador YouTube)' },
  { id: 'es-MX-JorgeNeural', name: '🇲🇽 Jorge Neural (ES-MX • Narrador Grave)' },
  { id: 'es-MX-DaliaNeural', name: '🇲🇽 Dalia Neural (ES-MX • Natural / Storytelling)' },
];

export const GEMINI_EXPRESSIVE_VOICES: VoiceOption[] = [
  { id: 'Puck', name: 'Puck (Masculino • Energético / Comédia)' },
  { id: 'Charon', name: 'Charon (Masculino • Grave / Épico / Chefe)' },
  { id: 'Fenrir', name: 'Fenrir (Masculino • Intenso / Dramático)' },
  { id: 'Orus', name: 'Orus (Masculino • Firme / Narrador)' },
  { id: 'Kore', name: 'Kore (Feminino • Firme / Comercial)' },
  { id: 'Aoede', name: 'Aoede (Feminino • Expressiva / Storytelling)' },
  { id: 'Zephyr', name: 'Zephyr (Feminino • Jovem / Dinâmica)' },
  { id: 'Leda', name: 'Leda (Feminino • Suave / Elegante)' },
];

export const KOKORO_VOICES: VoiceOption[] = [
  { id: 'pm_alex', name: '🎙️ pm_alex (PT-BR Masculino Grave • Local)' },
  { id: 'pf_dora', name: '🎙️ pf_dora (PT-BR Feminino Natural • Local)' },
  { id: 'pm_santa', name: '🎙️ pm_santa (PT-BR Histórias / Sombrio • Local)' },
  { id: 'af_heart', name: '🎙️ af_heart (EN-US Feminino Expressivo • Local)' },
  { id: 'am_adam', name: '🎙️ am_adam (EN-US Masculino Narrador • Local)' },
];

export const FLOW_MODES = {
  economico_pro: {
    id: 'economico_pro',
    label: '🟢 Econômico Pro (Nano Banana 2 + 2.5D CPU)',
    est_credits: 0,
  },
  gancho_de_ouro: {
    id: 'gancho_de_ouro',
    label: '🟡 Gancho de Ouro (~15 cr • Veo 3.1 Cena 1)',
    est_credits: 15,
  },
  cinema_full_veo: {
    id: 'cinema_full_veo',
    label: '🔴 Cinema Full Veo (Com Teto de Créditos)',
    est_credits: 45,
  },
};
