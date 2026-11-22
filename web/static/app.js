/* FrimeRise Dashboard Client Logic — 3 Master Engines + Estúdio de Criação Personalizada + Twin Channels + DNA X-Ray + Google Flow Pro */
let STATE = {
  settings: {},
  presets: [],
  clients: [],
  skills: [],
  luts: [],
  music: [],
  edge_voices: [],
  edge_voices_all: [],
  gemini_voices: [],
  kokoro_voices: [],
  visual_libraries_catalog: [],
  duration_presets: [],
  caption_styles: [],
  flow_pro: { credits_remaining: 10000, credits_total: 10000 },
  doc_queue: { channels: {}, episodes: [] },
  jobs: [],
  schedules: [],
  feedback: [],
  activeMode: 'single',
  activeStyle: 'cinematic_broll',
  selectedVipJobId: null,
  lastAnalyzedDna: null,
  userCustomizedLibs: false,
};

const DEFAULT_GEMINI_VOICES = [
  { id: 'Puck', name: 'Puck (Masculino • Energético / Comédia)' },
  { id: 'Charon', name: 'Charon (Masculino • Grave / Épico / Chefe)' },
  { id: 'Fenrir', name: 'Fenrir (Masculino • Intenso / Dramático)' },
  { id: 'Orus', name: 'Orus (Masculino • Firme / Narrador)' },
  { id: 'Kore', name: 'Kore (Feminino • Firme / Comercial)' },
  { id: 'Aoede', name: 'Aoede (Feminino • Expressiva / Storytelling)' },
  { id: 'Zephyr', name: 'Zephyr (Feminino • Jovem / Dinâmica)' },
  { id: 'Leda', name: 'Leda (Feminino • Suave / Elegante)' },
];

const DEFAULT_EDGE_VOICES = [
  { id: 'pt-BR-AntonioNeural', name: '🇧🇷 Antonio Neural (PT-BR • Grave / Documentário)' },
  { id: 'pt-BR-FranciscaNeural', name: '🇧🇷 Francisca Neural (PT-BR • Clara / Comercial)' },
  { id: 'pt-BR-ThalitaMultilingualNeural', name: '🇧🇷 Thalita Multilingual (PT-BR • Expressiva)' },
  { id: 'en-US-AndrewMultilingualNeural', name: '🇺🇸 Andrew Multilingual (EN-US • Vault Files Grave)' },
  { id: 'en-US-AvaMultilingualNeural', name: '🇺🇸 Ava Multilingual (EN-US • Expressiva)' },
  { id: 'en-US-GuyNeural', name: '🇺🇸 Guy Neural (EN-US • Narrador YouTube)' },
  { id: 'es-MX-JorgeNeural', name: '🇲🇽 Jorge Neural (ES-MX • Narrador Grave)' },
  { id: 'es-MX-DaliaNeural', name: '🇲🇽 Dalia Neural (ES-MX • Natural / Storytelling)' },
];

const DEFAULT_KOKORO_VOICES = [
  { id: 'pm_alex', name: '🎙️ pm_alex (PT-BR Masculino Grave • Local)' },
  { id: 'pf_dora', name: '🎙️ pf_dora (PT-BR Feminino Natural • Local)' },
  { id: 'pm_santa', name: '🎙️ pm_santa (PT-BR Histórias / Sombrio • Local)' },
  { id: 'af_heart', name: '🎙️ af_heart (EN-US Feminino Expressivo • Local)' },
  { id: 'am_adam', name: '🎙️ am_adam (EN-US Masculino Narrador • Local)' },
];

const LIBRARY_MIX_PRESETS = {
  cinema_real: ['real_broll', 'photos_25d', 'video_over_video', 'skia_graphics', 'cinema_35mm_sfx'],
  antistock_ai: ['bespoke_ai', 'photos_25d', 'skia_graphics', 'cinema_35mm_sfx'],
  cartoon_real: ['cartoon_2d_layer', 'real_broll', 'skia_graphics', 'cinema_35mm_sfx'],
  all_layers: ['real_broll', 'photos_25d', 'video_over_video', 'skia_graphics', 'cartoon_2d_layer', 'bespoke_ai', 'cinema_35mm_sfx'],
};

function normalizeVoiceList(rawList, fallbackList) {
  const seen = new Set();
  const out = [];
  const fallbackMap = new Map((fallbackList || []).map((v) => [v.id, v.name]));
  const pushItem = (item) => {
    if (!item) return;
    const id = typeof item === 'string' ? item : item.id;
    if (!id || seen.has(id)) return;
    seen.add(id);
    const name = typeof item === 'string'
      ? (fallbackMap.get(id) || id)
      : (item.name || item.label || fallbackMap.get(id) || id);
    out.push({ id, name });
  };
  (rawList || []).forEach(pushItem);
  (fallbackList || []).forEach(pushItem);
  return out;
}

function showToast(msg, isError = false) {
  const box = document.getElementById('toast-box');
  if (!box) return;
  box.textContent = msg;
  box.style.borderColor = isError ? '#FF2E93' : '#B8FF01';
  box.style.color = isError ? '#FFB3D9' : '#B8FF01';
  box.classList.remove('hidden');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => box.classList.add('hidden'), 4800);
}

async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (res.status === 401) {
    const nextUrl = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${nextUrl}`;
    throw new Error('Sessão expirada. Redirecionando para o login...');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Erro HTTP ${res.status}`);
  }
  return data;
}

/* -------------------- Tabs & Modes -------------------- */
document.querySelectorAll('.nav-tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    const target = btn.dataset.tab;
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.add('hidden'));
    document.getElementById(`tab-${target}`).classList.remove('hidden');
  });
});

function updateManufactureCtaText() {
  const cta = document.getElementById('btn-manufacture');
  if (!cta) return;
  if (STATE.activeMode === 'batch') {
    cta.innerHTML = '<span>⚡ FABRICAR LOTE DE VÍDEOS</span>';
  } else if (STATE.activeMode === 'clone_url') {
    cta.innerHTML = '<span>🧬 CLONAR DNA & FABRICAR VÍDEO</span>';
  } else if (STATE.activeStyle === 'cartoon_2d') {
    cta.innerHTML = '<span>🎭 FABRICAR ANIMAÇÃO 2D CARTOON</span>';
  } else if (STATE.activeStyle === 'netflix_doc') {
    cta.innerHTML = '<span>🎞️ FABRICAR DOCUMENTÁRIO CINEMA NETFLIX</span>';
  } else {
    cta.innerHTML = '<span>⚡ FABRICAR VÍDEO DINÂMICO / BESPOKE 2.5D</span>';
  }
}

document.querySelectorAll('.mode-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    STATE.activeMode = btn.dataset.mode;
    document.querySelectorAll('.mode-btn').forEach((b) => {
      b.classList.remove('bg-frimepink', 'text-white');
      b.classList.add('text-[#B6A9D4]');
    });
    btn.classList.add('bg-frimepink', 'text-white');
    btn.classList.remove('text-[#B6A9D4]');

    document.getElementById('mode-single-wrap').classList.toggle('hidden', STATE.activeMode !== 'single');
    document.getElementById('mode-batch-wrap').classList.toggle('hidden', STATE.activeMode !== 'batch');
    document.getElementById('mode-clone-wrap').classList.toggle('hidden', STATE.activeMode !== 'clone_url');
    updateManufactureCtaText();
  });
});

function selectEngineStyle(style) {
  STATE.activeStyle = style;
  document.querySelectorAll('.style-btn').forEach((b) => {
    const isSel = b.dataset.style === style;
    b.classList.toggle('border-frimelime', isSel);
    b.classList.toggle('bg-[#0B0713]/90', isSel);
    b.classList.toggle('border-[rgba(179,136,255,0.22)]', !isSel);
  });
  document.getElementById('cartoon-2d-options').classList.toggle('hidden', style !== 'cartoon_2d');
  document.getElementById('netflix-doc-options').classList.toggle('hidden', style !== 'netflix_doc');

  const sk = document.getElementById('fac-skill');
  if (sk) {
    if (style === 'cartoon_2d') {
      const match = Array.from(sk.options).find((o) => o.value.includes('09_cartoon'));
      if (match) sk.value = match.value;
    } else if (style === 'netflix_doc') {
      const match = Array.from(sk.options).find((o) => o.value.includes('10_netflix'));
      if (match) sk.value = match.value;
      syncDocChannelSelection(false);
    }
  }

  // Sync universal aspect ratio, FPS, duration, caption style, and default library mix sensibly when switching Master Engine
  if (style === 'netflix_doc') {
    const docAsp = document.getElementById('doc-aspect')?.value || '16:9';
    syncUniversalAspectFrom(docAsp);
    // Auto-select 17 min (1020s) Cinema v3.0.0 long-form default when coming from short default <= 60s
    const curDur = Number(document.getElementById('fac-duration-s')?.value || 30);
    if (curDur <= 60) {
      setFactoryDuration(1020, 'engine');
    }
    const capEl = document.getElementById('fac-caption-style');
    if (capEl) {
      const targetCap = docAsp === '16:9' ? 'selective_emphasis' : 'cinema_minimal';
      if (Array.from(capEl.options).some((o) => o.value === targetCap)) {
        capEl.value = targetCap;
      }
    }
    if (!STATE.userCustomizedLibs) {
      applyLibraryMixValues(['real_broll', 'photos_25d', 'video_over_video', 'skia_graphics', 'cinema_35mm_sfx'], false);
    }
  } else if (style === 'cartoon_2d') {
    const cAsp = document.getElementById('fac-aspect')?.value || '9:16';
    syncUniversalAspectFrom(cAsp);
    const fpsUni = document.getElementById('fac-fps-universal');
    const fpsCart = document.getElementById('fac-fps');
    if (fpsUni && fpsCart) {
      fpsUni.value = '60';
      fpsCart.value = '60';
    }
    if (!STATE.userCustomizedLibs) {
      applyLibraryMixValues(['cartoon_2d_layer', 'skia_graphics', 'cinema_35mm_sfx'], false);
    }
  } else {
    const curAsp = document.getElementById('fac-aspect-universal')?.value || '9:16';
    if (curAsp === '16:9') {
      syncUniversalAspectFrom('9:16');
    }
    if (!STATE.userCustomizedLibs) {
      applyLibraryMixValues(['real_broll', 'photos_25d', 'skia_graphics', 'cinema_35mm_sfx'], false);
    }
  }

  updateAdvancedSummaryPill();
  updateRecipeSummary();
  updateManufactureCtaText();
}

document.querySelectorAll('.style-btn').forEach((btn) => {
  btn.addEventListener('click', () => selectEngineStyle(btn.dataset.style));
});

function syncDocChannelSelection(fromDocSelect = false) {
  const docLangEl = document.getElementById('doc-lang');
  const facLangEl = document.getElementById('fac-language');
  const lang = docLangEl?.value || 'pt_br';
  if (fromDocSelect && facLangEl && (lang === 'pt_br' || lang === 'en_us')) {
    facLangEl.value = lang;
  }
  const targetName = lang === 'en_us' ? 'Vault Files' : 'Dossiê Capital';
  const found = (STATE.clients || []).find((c) => c.name === targetName);
  const cliSel = document.getElementById('fac-client');
  if (found && cliSel) {
    cliSel.value = String(found.id);
    onFactoryClientChange();
  }
  updateRecipeSummary();
}

/* -------------------- Estúdio de Criação Personalizada (Tab 1) -------------------- */
function getSelectedFactoryClient() {
  const cid = String(document.getElementById('fac-client')?.value || '');
  return (STATE.clients || []).find((c) => String(c.id) === cid) || (STATE.clients || [])[0] || null;
}

function getAllVoicePools() {
  const gemini = normalizeVoiceList(STATE.gemini_voices, DEFAULT_GEMINI_VOICES);
  const edge = normalizeVoiceList(
    (STATE.edge_voices_all && STATE.edge_voices_all.length) ? STATE.edge_voices_all : STATE.edge_voices,
    DEFAULT_EDGE_VOICES
  );
  const kokoro = normalizeVoiceList(STATE.kokoro_voices, DEFAULT_KOKORO_VOICES);
  return { gemini, edge, kokoro };
}

function syncFactoryVoiceList(preferredVoiceId = null) {
  const engEl = document.getElementById('fac-voice-engine');
  const vSel = document.getElementById('fac-voice-id');
  if (!engEl || !vSel) return;

  const eng = engEl.value || 'auto';
  const prev = preferredVoiceId !== null ? preferredVoiceId : vSel.value;
  const pools = getAllVoicePools();
  const client = getSelectedFactoryClient();

  if (eng === 'auto') {
    const clientVoiceLabel = client ? `${client.voice_id || 'pt-BR-AntonioNeural'} (${client.voice_engine || 'edge'})` : 'Automática';
    vSel.innerHTML = `
      <option value="">✨ Padrão do Cliente — ${clientVoiceLabel}</option>
      <optgroup label="🎭 Google Gemini TTS Expressivo">
        ${pools.gemini.map((v) => `<option value="${v.id}">${v.name}</option>`).join('')}
      </optgroup>
      <optgroup label="⚡ Edge-TTS Neural (PT-BR / EN-US / ES)">
        ${pools.edge.map((v) => `<option value="${v.id}">${v.name}</option>`).join('')}
      </optgroup>
      <optgroup label="🎙️ Kokoro-ONNX Voice Blender Local">
        ${pools.kokoro.map((v) => `<option value="${v.id}">${v.name}</option>`).join('')}
      </optgroup>
    `;
    const allIds = ['', ...pools.gemini.map((v) => v.id), ...pools.edge.map((v) => v.id), ...pools.kokoro.map((v) => v.id)];
    vSel.value = allIds.includes(prev) ? prev : '';
  } else {
    const list = eng === 'gemini_tts' ? pools.gemini : (eng === 'kokoro' ? pools.kokoro : pools.edge);
    vSel.innerHTML = list.map((v) => `<option value="${v.id}">${v.name}</option>`).join('');
    if (prev && list.some((v) => v.id === prev)) {
      vSel.value = prev;
    } else if (list.length > 0) {
      // Pick language-matching default when Edge-TTS is selected
      if (eng === 'edge') {
        const lang = document.getElementById('fac-language')?.value || 'pt_br';
        const wanted = lang === 'en_us' ? 'en-US-AndrewMultilingualNeural' : (lang === 'es' ? 'es-MX-DaliaNeural' : 'pt-BR-AntonioNeural');
        vSel.value = list.some((v) => v.id === wanted) ? wanted : list[0].id;
      } else {
        vSel.value = list[0].id;
      }
    }
  }

  // Keep Cartoon 2D voice selector synced when applicable
  const cVoice = document.getElementById('fac-cartoon-voice');
  if (cVoice && (eng === 'gemini_tts' || eng === 'edge')) {
    cVoice.value = eng;
  }
  updateRecipeSummary();
}

function syncCartoonVoiceEngine() {
  const cVoice = document.getElementById('fac-cartoon-voice');
  const fEng = document.getElementById('fac-voice-engine');
  if (cVoice && fEng) {
    fEng.value = cVoice.value;
    syncFactoryVoiceList();
  }
}

function resolveEffectiveFactoryVoice() {
  const engRaw = document.getElementById('fac-voice-engine')?.value || 'auto';
  const voiceRaw = document.getElementById('fac-voice-id')?.value || '';
  const pools = getAllVoicePools();
  const client = getSelectedFactoryClient();

  if (engRaw !== 'auto') {
    const fallbackId = engRaw === 'gemini_tts' ? 'Puck' : (engRaw === 'kokoro' ? 'pm_alex' : 'pt-BR-AntonioNeural');
    return { voice_engine: engRaw, voice_id: voiceRaw || fallbackId };
  }
  if (voiceRaw) {
    if (pools.gemini.some((v) => v.id === voiceRaw)) return { voice_engine: 'gemini_tts', voice_id: voiceRaw };
    if (pools.kokoro.some((v) => v.id === voiceRaw)) return { voice_engine: 'kokoro', voice_id: voiceRaw };
    return { voice_engine: 'edge', voice_id: voiceRaw };
  }
  if (STATE.activeStyle === 'netflix_doc' && STATE.settings?.gemini_api_key) {
    return { voice_engine: 'gemini_tts', voice_id: 'Charon' };
  }
  return {
    voice_engine: client?.voice_engine || 'edge',
    voice_id: client?.voice_id || 'pt-BR-AntonioNeural',
  };
}

async function previewFactoryVoice() {
  const btn = document.getElementById('btn-fac-voice-preview');
  const audio = document.getElementById('fac-voice-audio');
  if (!btn || !audio) return;

  const { voice_engine, voice_id } = resolveEffectiveFactoryVoice();
  const voice_rate = document.getElementById('fac-voice-rate')?.value || '+8%';
  const voice_pitch = document.getElementById('fac-voice-pitch')?.value || '+0Hz';
  const lang = document.getElementById('fac-language')?.value || 'pt_br';
  const customTopic = (document.getElementById('fac-topic')?.value || '').trim();

  const defaultSamples = {
    pt_br: 'Atenção! Esta é a prévia oficial da sua voz escolhida no estúdio FrimeRise, pronta para transformar qualquer ideia em um vídeo de cinema.',
    en_us: 'Attention! This is the live preview of your selected FrimeRise voice, calibrated for high-retention storytelling and broadcast clarity.',
    es: '¡Atención! Esta es la vista previa en vivo de tu voz elegida en FrimeRise, calibrada para máxima retención y calidad cinematográfica.',
  };
  const sample_text = customTopic
    ? (lang === 'en_us'
        ? `Tonight we uncover the hidden story behind: ${customTopic.slice(0, 120)}.`
        : lang === 'es'
          ? `Hoy revelamos la historia oculta detrás de: ${customTopic.slice(0, 120)}.`
          : `Hoje você vai descobrir a verdade oculta por trás de: ${customTopic.slice(0, 120)}.`)
    : (defaultSamples[lang] || defaultSamples.pt_br);

  btn.disabled = true;
  btn.textContent = '⏳ Gerando voz...';
  try {
    const res = await api('/api/voice/preview', {
      method: 'POST',
      body: JSON.stringify({
        voice_engine,
        voice_id,
        voice_rate,
        voice_pitch,
        voice_blend: {
          pf_dora: Number(document.getElementById('blend-dora')?.value || 35) / 100,
          pm_alex: Number(document.getElementById('blend-alex')?.value || 65) / 100,
          pm_santa: Number(document.getElementById('blend-santa')?.value || 0) / 100,
        },
        sample_text,
      }),
    });
    audio.src = `${res.audio_url}?t=${Date.now()}`;
    audio.classList.remove('hidden');
    await audio.play().catch(() => {});
    showToast(`🎙️ Prévia pronta (${voice_id} • ${voice_rate} • ${voice_pitch} • ${res.duration_s}s)`);
  } catch (e) {
    showToast(`Erro na prévia de voz: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Ouvir Voz';
  }
}

function onFactoryClientChange() {
  const eng = document.getElementById('fac-voice-engine')?.value || 'auto';
  if (eng === 'auto') {
    syncFactoryVoiceList(document.getElementById('fac-voice-id')?.value || '');
  }
  onFactoryPresetChange();
  updateRecipeSummary();
}

function formatDurationLabel(seconds) {
  const s = Math.max(10, Math.min(1200, Math.round(Number(seconds) || 30)));
  if (s <= 20) return `${s}s • Gancho Relâmpago`;
  if (s <= 45) return `${s}s • Viral Curto`;
  if (s <= 90) return `${s}s • Shorts / Reels Completo`;
  const mins = Number((s / 60).toFixed(1));
  if (s <= 240) return `${mins} min • YouTube Mini-Doc`;
  if (s <= 600) return `${mins} min • Mid-Roll Alto RPM`;
  return `${mins} min • Documentário Cinema v3`;
}

function setFactoryDuration(val, source = 'pill') {
  const parsed = Number(val);
  const clamped = Number.isFinite(parsed) ? Math.max(10, Math.min(1200, Math.round(parsed))) : 30;
  const numEl = document.getElementById('fac-duration-s');
  const rngEl = document.getElementById('fac-duration-range');
  const lblEl = document.getElementById('fac-duration-label');

  if (numEl && source !== 'number') numEl.value = String(clamped);
  if (rngEl && source !== 'range') {
    rngEl.value = String(Math.max(15, clamped));
  }
  if (rngEl) {
    const pct = Math.max(0, Math.min(100, ((Math.max(15, clamped) - 15) / (1200 - 15)) * 100));
    rngEl.style.setProperty('--progress', `${pct.toFixed(1)}%`);
  }
  if (lblEl) {
    lblEl.textContent = formatDurationLabel(clamped);
  }

  document.querySelectorAll('.dur-pill-btn').forEach((btn) => {
    btn.classList.toggle('active', Number(btn.dataset.seconds) === clamped);
  });

  // Sync Netflix Doc duration select to closest value when not coming from doc select
  const docMin = document.getElementById('doc-minutes');
  if (docMin && source !== 'doc') {
    const mins = clamped / 60;
    const opts = Array.from(docMin.options).map((o) => Number(o.value));
    const nearest = opts.reduce((best, cur) => (Math.abs(cur - mins) < Math.abs(best - mins) ? cur : best), opts[0]);
    docMin.value = String(nearest);
  }
  updateRecipeSummary();
}

function syncDurationFromDocMinutes() {
  const mins = Number(document.getElementById('doc-minutes')?.value || 17.0);
  setFactoryDuration(Math.round(mins * 60), 'doc');
}

function onUniversalAspectChange() {
  const ratio = document.getElementById('fac-aspect-universal')?.value || '9:16';
  const cAsp = document.getElementById('fac-aspect');
  const dAsp = document.getElementById('doc-aspect');
  if (cAsp && Array.from(cAsp.options).some((o) => o.value === ratio)) cAsp.value = ratio;
  if (dAsp && Array.from(dAsp.options).some((o) => o.value === ratio)) dAsp.value = ratio;
  if (STATE.activeStyle === 'netflix_doc') {
    const capEl = document.getElementById('fac-caption-style');
    if (capEl) {
      const targetCap = ratio === '16:9' ? 'selective_emphasis' : 'cinema_minimal';
      if (Array.from(capEl.options).some((o) => o.value === targetCap)) {
        capEl.value = targetCap;
      }
    }
  }
  updateRecipeSummary();
}

function syncUniversalAspectFrom(ratio) {
  const uni = document.getElementById('fac-aspect-universal');
  const cAsp = document.getElementById('fac-aspect');
  const dAsp = document.getElementById('doc-aspect');
  if (uni && Array.from(uni.options).some((o) => o.value === ratio)) uni.value = ratio;
  if (cAsp && Array.from(cAsp.options).some((o) => o.value === ratio)) cAsp.value = ratio;
  if (dAsp && Array.from(dAsp.options).some((o) => o.value === ratio)) dAsp.value = ratio;
  updateRecipeSummary();
}

function onFactoryLanguageChange() {
  const lang = document.getElementById('fac-language')?.value || 'pt_br';
  const docLang = document.getElementById('doc-lang');
  if (docLang && (lang === 'pt_br' || lang === 'en_us')) {
    docLang.value = lang;
    if (STATE.activeStyle === 'netflix_doc') {
      syncDocChannelSelection(false);
    }
  }
  // If user is on Edge-TTS, auto-switch voice to match chosen language
  const vEng = document.getElementById('fac-voice-engine')?.value || 'auto';
  const vSel = document.getElementById('fac-voice-id');
  if (vEng === 'edge' && vSel) {
    const targetVoice = lang === 'en_us' ? 'en-US-AndrewMultilingualNeural' : (lang === 'es' ? 'es-MX-DaliaNeural' : 'pt-BR-AntonioNeural');
    if (Array.from(vSel.options).some((o) => o.value === targetVoice)) {
      vSel.value = targetVoice;
    }
  }
  updateRecipeSummary();
}

function onFactoryPresetChange() {
  const box = document.getElementById('fac-preset-swatches');
  if (!box) return;
  const presetId = document.getElementById('fac-preset')?.value || '';
  const client = getSelectedFactoryClient();
  const effectiveId = presetId || client?.preset_id || 'frimerise_signature';
  const p = (STATE.presets || []).find((x) => x.id === effectiveId);
  if (p) {
    box.innerHTML = `
      <span class="w-3.5 h-3.5 rounded-full inline-block shrink-0" style="background:${p.primary_color}"></span>
      <span class="w-3.5 h-3.5 rounded-full inline-block shrink-0" style="background:${p.secondary_color}"></span>
      <span class="w-3.5 h-3.5 rounded-full inline-block shrink-0" style="background:${p.highlight_color}"></span>
      <span class="w-3.5 h-3.5 rounded-full inline-block shrink-0" style="background:${p.accent_gold}"></span>
      <span class="truncate text-white font-semibold">${p.name}</span>
    `;
  }
  updateRecipeSummary();
}

/* -------------------- Misturador de Bibliotecas ("Misturar Bibliotecas") -------------------- */
function getSelectedVisualLibraries() {
  return Array.from(document.querySelectorAll('.lib-mix-check:checked')).map((el) => el.value);
}

function updateLibraryMixCount() {
  const boxes = Array.from(document.querySelectorAll('.lib-mix-check'));
  let count = 0;
  boxes.forEach((cb) => {
    const card = cb.closest('.lib-mix-card');
    if (card) card.classList.toggle('active', cb.checked);
    if (cb.checked) count += 1;
  });

  const badge = document.getElementById('lib-mix-count');
  if (badge) {
    if (count === 0) {
      badge.textContent = '⚠️ Selecione ao menos 1 biblioteca';
      badge.className = 'text-[11px] font-extrabold px-2.5 py-0.5 rounded-full bg-frimepink/20 text-frimepink border border-frimepink/50';
    } else {
      badge.textContent = count === 1 ? '1 biblioteca ativa no mix' : `${count} bibliotecas ativas no mix`;
      badge.className = 'text-[11px] font-extrabold px-2.5 py-0.5 rounded-full bg-frimelime/15 text-frimelime border border-frimelime/45';
    }
  }
  const recipePill = document.getElementById('recipe-mix-pill');
  if (recipePill) {
    recipePill.textContent = count === 1 ? '1 biblioteca' : `${count} bibliotecas`;
  }
  updateRecipeSummary();
}

function applyLibraryMixValues(values, markCustomized = true) {
  const wanted = new Set(values || []);
  document.querySelectorAll('.lib-mix-check').forEach((cb) => {
    cb.checked = wanted.has(cb.value);
  });
  const optMotion = document.getElementById('opt-motion');
  if (optMotion) {
    optMotion.checked = wanted.has('skia_graphics');
  }
  if (markCustomized) {
    STATE.userCustomizedLibs = true;
  }
  updateLibraryMixCount();
}

function applyLibraryMixPreset(presetKey, btnEl = null) {
  const list = LIBRARY_MIX_PRESETS[presetKey] || LIBRARY_MIX_PRESETS.cinema_real;
  applyLibraryMixValues(list, true);
  document.querySelectorAll('.mix-preset-btn').forEach((b) => {
    b.classList.toggle('active', b === btnEl || b.dataset.mix === presetKey);
  });
  showToast(`🧩 Mix aplicado: ${list.length} bibliotecas combinadas!`);
}

function onLibraryMixToggle(checkbox) {
  STATE.userCustomizedLibs = true;
  document.querySelectorAll('.mix-preset-btn').forEach((b) => b.classList.remove('active'));
  if (checkbox && checkbox.value === 'skia_graphics') {
    const optMotion = document.getElementById('opt-motion');
    if (optMotion) optMotion.checked = checkbox.checked;
  }
  updateLibraryMixCount();
}

function syncMotionCardWithSkia() {
  const optMotion = document.getElementById('opt-motion');
  const libSkia = document.getElementById('lib-skia_graphics');
  if (optMotion && libSkia) {
    libSkia.checked = optMotion.checked;
    updateLibraryMixCount();
  }
}

/* -------------------- Configurações Avançadas (<details>) -------------------- */
function syncFpsControl(sourceId) {
  const src = document.getElementById(sourceId);
  const uni = document.getElementById('fac-fps-universal');
  const cart = document.getElementById('fac-fps');
  if (!src) return;
  if (uni && sourceId !== 'fac-fps-universal') uni.value = src.value;
  if (cart && sourceId !== 'fac-fps') cart.value = src.value;
  updateAdvancedSummaryPill();
  updateRecipeSummary();
}

function onMusicFileChange() {
  const val = document.getElementById('fac-music-file')?.value || 'auto';
  const flowMusicCb = document.getElementById('opt-flow-music');
  if (flowMusicCb) {
    if (val === 'flow_vault') flowMusicCb.checked = true;
    else if (val === 'none' || val.endsWith('.mp3')) flowMusicCb.checked = false;
  }
  updateAdvancedSummaryPill();
  updateRecipeSummary();
}

function onFlowMusicCheckboxChange() {
  const flowMusicCb = document.getElementById('opt-flow-music');
  const musicSel = document.getElementById('fac-music-file');
  if (!flowMusicCb || !musicSel) return;
  if (flowMusicCb.checked) {
    if (musicSel.value === 'auto' || musicSel.value === 'none') {
      musicSel.value = 'flow_vault';
    }
  } else if (musicSel.value === 'flow_vault') {
    musicSel.value = 'auto';
  }
  updateAdvancedSummaryPill();
  updateRecipeSummary();
}

function updateMusicVolLabel() {
  const range = document.getElementById('fac-music-vol');
  const lbl = document.getElementById('fac-music-vol-label');
  if (!range || !lbl) return;
  const val = Number(range.value || 18);
  lbl.textContent = `${val}%`;
  const pct = Math.max(0, Math.min(100, (val / 40) * 100));
  range.style.setProperty('--progress', `${pct.toFixed(1)}%`);
  updateAdvancedSummaryPill();
}

function updateAdvancedSummaryPill() {
  const pill = document.getElementById('fac-adv-summary-pill');
  if (!pill) return;
  const fps = document.getElementById('fac-fps-universal')?.value || '30';
  const cadence = document.getElementById('fac-cut-cadence')?.value || '3.5';
  const music = document.getElementById('fac-music-file')?.value || 'auto';
  const vol = document.getElementById('fac-music-vol')?.value || '18';
  const musicLbl = music === 'none' ? 'Sem Trilha' : (music === 'flow_vault' ? 'Flow Music' : (music === 'auto' ? `Trilha Auto (${vol}%)` : `${music.replace('.mp3', '')} (${vol}%)`));
  pill.textContent = `${fps} FPS • ${cadence}s • ${musicLbl}`;
}

function updateRecipeSummary() {
  const box = document.getElementById('recipe-summary-lines');
  if (!box) return;
  const engLabels = {
    cinematic_broll: '🎬 Dinâmico / Bespoke 2.5D',
    cartoon_2d: '🎭 Cartoon 2D',
    netflix_doc: '🎞️ Doc Cinema Netflix',
  };
  const capLabels = {
    hormozi_neon: 'Hormozi Neon Spring',
    karaoke_glow: 'Karaokê Glow',
    word_slam: 'Word Slam 3D',
    selective_emphasis: 'Selective Emphasis (Doc 16:9)',
    cinema_minimal: 'Cinema Minimalista',
    typewriter_highlight: 'Dossiê Typewriter',
    none: 'Sem Legendas',
  };
  const { voice_engine, voice_id } = resolveEffectiveFactoryVoice();
  const rate = document.getElementById('fac-voice-rate')?.value || '+8%';
  const pitch = document.getElementById('fac-voice-pitch')?.value || '+0Hz';
  const aspect = document.getElementById('fac-aspect-universal')?.value || '9:16';
  const dur = Number(document.getElementById('fac-duration-s')?.value || 30);
  const cap = document.getElementById('fac-caption-style')?.value || 'hormozi_neon';
  const lang = (document.getElementById('fac-language')?.value || 'pt_br').toUpperCase().replace('_', '-');
  const fps = document.getElementById('fac-fps-universal')?.value || '30';
  const libs = getSelectedVisualLibraries();
  const directives = (document.getElementById('fac-custom-directives')?.value || '').trim();

  box.innerHTML = `
    <div><strong class="text-white">${engLabels[STATE.activeStyle] || STATE.activeStyle}</strong> • <span class="text-frimelime font-bold">${aspect}</span> • <span class="text-frimegold font-bold">${formatDurationLabel(dur)}</span> • ${fps} FPS • ${lang}</div>
    <div>🎙️ <span class="text-frimepink font-bold">${voice_id}</span> (${voice_engine} • ${rate} / ${pitch}) • 💬 <span class="text-frimelilac">${capLabels[cap] || cap}</span></div>
    <div>🧩 Mix: <span class="text-white">${libs.length ? libs.join(', ') : 'Nenhuma selecionada'}</span>${directives ? ' • ✍️ <span class="text-frimegold">Diretrizes extras ativas</span>' : ''}</div>
  `;
}

/* -------------------- Google Flow & Flow Music Pro Controls -------------------- */
function toggleFlowCreditsCap() {
  const mode = document.getElementById('fac-flow-mode')?.value || 'economico_pro';
  const capInput = document.getElementById('fac-flow-cap');
  const pill = document.getElementById('flow-mode-pill');
  if (!capInput || !pill) return;
  if (mode === 'economico_pro') {
    pill.textContent = '🟢 0 Créditos Veo • 2.5D CPU + Nano Banana 2';
    pill.className = 'text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-frimelime/15 text-frimelime border border-frimelime/40';
  } else if (mode === 'gancho_de_ouro') {
    pill.textContent = '🟡 ~15 Créditos • Cena 1 Veo 3.1 Light + 2.5D CPU';
    pill.className = 'text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-frimegold/20 text-frimegold border border-frimegold/45';
  } else {
    pill.textContent = `🔴 Teto Ativo: máx ${capInput.value || 45} cr • Cofre FlowVault`;
    pill.className = 'text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-frimepink/20 text-frimepink border border-frimepink/45';
  }
}

async function loginGoogleFlow(target = 'flow') {
  try {
    const res = await api('/api/flow/login', {
      method: 'POST',
      body: JSON.stringify({ target, warm_seconds: 180 }),
    });
    showToast(`🌊 ${res.message}`);
  } catch (e) {
    showToast(`Erro ao iniciar login Google Flow: ${e.message}`, true);
  }
}

/* -------------------- Multimodal Cloner: URL + Upload .mp4 + Visual DNA X-Ray -------------------- */
function renderDnaXrayPanel(dna) {
  if (!dna) return;
  STATE.lastAnalyzedDna = dna;
  const panel = document.getElementById('dna-xray-panel');
  const badge = document.getElementById('dna-status-badge');
  const pill = document.getElementById('dna-engine-pill');
  const img = document.getElementById('dna-contact-sheet-img');
  const metrics = document.getElementById('dna-metrics-text');
  const swatches = document.getElementById('dna-palette-swatches');
  const presetInput = document.getElementById('dna-preset-name');

  panel.classList.remove('hidden');
  const eng = dna.classified_engine || (dna.style === '2d_cartoon_animation' ? 'cartoon_2d' : 'cinematic_broll');
  const engLabels = {
    cinematic_broll: '🎬 Vídeo Dinâmico Viral / Bespoke 2.5D',
    cartoon_2d: '🎭 Animação 2D Cartoon Multi-Personagens',
    netflix_doc: '🎞️ Documentário Cinema Netflix / MagnatesMedia',
  };
  pill.textContent = engLabels[eng] || eng;
  badge.innerHTML = `<strong class="text-frimelime">✔ DNA Extraído: ${engLabels[eng] || eng}</strong>`;

  if (dna.contact_sheet_url) {
    img.src = `${dna.contact_sheet_url}?t=${Date.now()}`;
  }

  const cadence = dna.scene_cadence || {};
  const optFlow = dna.optical_flow || {};
  const avgCut = cadence.avg_cut_seconds || dna.avg_scene_duration_s || 2.8;
  const cutsCount = cadence.cuts_count || (dna.scenes ? dna.scenes.length : 6);
  const domMotion = optFlow.dominant_motion || 'punch_in';
  metrics.innerHTML = `
    <div>⏱️ <strong>Cadência OpenCV:</strong> corte a cada <span class="text-frimelime font-bold">${avgCut}s</span> (${cutsCount} cenas • ${dna.duration_s || 25}s total)</div>
    <div>🎥 <strong>Optical Flow Farneback:</strong> movimento dominante <span class="text-frimegold font-bold">${domMotion}</span> (${dna.aspect_ratio || '9:16'})</div>
    <div>🎙️ <strong>Tom / Subtítulos:</strong> <span class="text-frimelilac">${dna.detected_tone || 'Alta Retenção'}</span></div>
  `;

  const palette = dna.dominant_palette || ['#0B0713', '#FF2E93', '#B8FF01', '#FFD166'];
  swatches.innerHTML = `<span class="text-[11px] text-[#B6A9D4] mr-1">Paleta HEX:</span>` + palette.map((hex) => `
    <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold border border-white/20" style="background:${hex};color:#fff;text-shadow:0 1px 2px #000">${hex}</span>
  `).join('');

  if (presetInput && !presetInput.value) {
    presetInput.value = `DNA ${(dna.title || 'Viral').slice(0, 22)}`;
  }

  selectEngineStyle(eng);
}

async function uploadReferenceMp4(input) {
  if (!input.files || !input.files[0]) return;
  const badge = document.getElementById('dna-status-badge');
  badge.textContent = '🧬 Extraindo Storyboard 3×3 + Cadência OpenCV + Whisper...';
  const fd = new FormData();
  fd.append('file', input.files[0]);
  try {
    const res = await fetch('/api/factory/upload-reference', { method: 'POST', body: fd });
    const data = await res.json();
    document.getElementById('fac-ref-mp4-path').value = data.reference_mp4_path;
    renderDnaXrayPanel(data.dna);
    showToast('🔬 Raio-X de DNA do arquivo .mp4 concluído!');
  } catch (e) {
    badge.textContent = 'Erro ao analisar MP4.';
    showToast('Falha ao analisar MP4 de referência.', true);
  }
}

async function analyzeReferenceUrl() {
  const url = document.getElementById('fac-url').value.trim();
  const refMp4 = document.getElementById('fac-ref-mp4-path').value.trim();
  if (!url && !refMp4) {
    return showToast('Cole uma URL concorrente ou envie um arquivo .mp4 primeiro.', true);
  }
  const btn = document.getElementById('btn-analyze-url');
  const badge = document.getElementById('dna-status-badge');
  btn.disabled = true;
  btn.textContent = '⏳ Analisando 3×3...';
  badge.textContent = '🧬 Baixando referência e gerando contact_sheet.jpg (OpenCV + Storyboard 3×3)...';
  try {
    const res = await api('/api/factory/analyze-url', {
      method: 'POST',
      body: JSON.stringify({ source_url: url, reference_mp4_path: refMp4 }),
    });
    renderDnaXrayPanel(res.dna);
    showToast('🔬 Raio-X Multimodal de DNA concluído com sucesso!');
  } catch (e) {
    badge.textContent = `Erro: ${e.message}`;
    showToast(`Falha no Raio-X de DNA: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '🧬 Raio-X DNA';
  }
}

async function saveDnaAsPreset() {
  const nameInput = document.getElementById('dna-preset-name');
  const presetName = (nameInput?.value || '').trim() || 'DNA Viral Clonado';
  const btn = document.getElementById('btn-save-dna-preset');
  btn.disabled = true;
  btn.textContent = '⏳ Salvando...';
  try {
    const res = await api('/api/factory/save-dna-preset', {
      method: 'POST',
      body: JSON.stringify({
        preset_name: presetName,
        blueprint: STATE.lastAnalyzedDna || {},
      }),
    });
    STATE.presets = res.presets || STATE.presets;
    if (res.preset && res.preset.id) {
      document.getElementById('cli-preset-id').value = res.preset.id;
    }
    renderSelectors();
    renderPresetsGrid();
    if (res.preset && res.preset.id) {
      const facPreset = document.getElementById('fac-preset');
      if (facPreset) {
        facPreset.value = res.preset.id;
        onFactoryPresetChange();
      }
    }
    showToast(`💾 Preset "${res.preset?.name || presetName}" salvo permanentemente no SQLite!`);
  } catch (e) {
    showToast(`Erro ao salvar DNA como Preset: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '💾 Salvar DNA como Novo Preset';
  }
}

/* -------------------- Twin Channels & 10-Episode Ready Queue -------------------- */
function renderDocQueue() {
  const dq = STATE.doc_queue || {};
  const channels = dq.channels || {};
  const episodes = dq.episodes || [];

  const headerCards = document.getElementById('twin-channels-header-cards');
  if (headerCards && (channels.pt_br || channels.en_us)) {
    const br = channels.pt_br || {};
    const us = channels.en_us || {};
    headerCards.innerHTML = `
      <div class="p-3 rounded-xl bg-[#0B0713]/90 border border-frimegold/45 space-y-1">
        <div class="flex items-center gap-2">
          <span class="text-sm font-black text-frimegold">🇧🇷 ${br.name || 'Dossiê Capital'}</span>
          <span class="text-[10px] px-2 py-0.5 rounded-full bg-frimegold/15 text-frimegold font-bold">${br.format || '16:9 Documentário Cinema'}</span>
        </div>
        <div class="text-[11px] text-[#B6A9D4]">LUT: <code class="text-frimelilac">${br.lut_file || '02_dark_wealth.cube'}</code> • Voz: <code class="text-frimelime">${br.voice_id || 'pt-BR-AntonioNeural'}</code> • Cascata: <strong>5 Shorts</strong></div>
      </div>
      <div class="p-3 rounded-xl bg-[#0B0713]/90 border border-frimelime/45 space-y-1">
        <div class="flex items-center gap-2">
          <span class="text-sm font-black text-frimelime">🇺🇸 ${us.name || 'Vault Files'}</span>
          <span class="text-[10px] px-2 py-0.5 rounded-full bg-frimelime/15 text-frimelime font-bold">${us.format || '16:9 Documentário Cinema'}</span>
        </div>
        <div class="text-[11px] text-[#B6A9D4]">LUT: <code class="text-frimelilac">${us.lut_file || '02_dark_wealth.cube'}</code> • Voz: <code class="text-frimegold">${us.voice_id || 'en-US-AndrewMultilingualNeural'}</code> • Cascata: <strong>5 Shorts</strong></div>
      </div>
    `;
  }

  const grid = document.getElementById('doc-queue-grid');
  if (!grid) return;
  if (!episodes.length) {
    grid.innerHTML = '<div class="text-xs text-[#B6A9D4]">Carregando fila de 10 documentários...</div>';
    return;
  }

  grid.innerHTML = episodes.map((ep) => `
    <div class="p-4 rounded-xl bg-[#0B0713]/90 border border-[rgba(179,136,255,0.25)] hover:border-frimegold/60 transition flex flex-col justify-between gap-3">
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-black px-2.5 py-0.5 rounded-full bg-frimepink/20 text-frimepink border border-frimepink/40">EPISÓDIO #${String(ep.id).padStart(2, '0')} • ${ep.category || 'Investigativo'}</span>
          <span class="text-[11px] font-extrabold text-frimelilac">${ep.short_name}</span>
        </div>
        <div class="text-xs font-bold text-white leading-snug">🇧🇷 ${ep.title_pt}</div>
        <div class="text-[11px] text-[#B6A9D4] leading-snug">🇺🇸 ${ep.title_en}</div>
        <div class="flex flex-wrap items-center gap-2 pt-1">
          <span class="text-[10px] font-black px-2 py-0.5 rounded bg-frimegold/15 text-frimegold border border-frimegold/35">🖼️ Thumb BR: "${ep.thumb_hook_pt}"</span>
          <span class="text-[10px] font-black px-2 py-0.5 rounded bg-frimelime/15 text-frimelime border border-frimelime/35">🖼️ Thumb US: "${ep.thumb_hook_en}"</span>
        </div>
      </div>
      <div class="grid grid-cols-3 gap-2 pt-2 border-t border-[rgba(179,136,255,0.14)]">
        <button type="button" onclick="launchDocQueueEpisode(${ep.id}, 'pt_br')" class="btn-ghost py-2 px-2 text-[11px] font-extrabold hover:border-frimegold text-frimegold">
          🇧🇷 Dossiê Capital
        </button>
        <button type="button" onclick="launchDocQueueEpisode(${ep.id}, 'en_us')" class="btn-ghost py-2 px-2 text-[11px] font-extrabold hover:border-frimelime text-frimelime">
          🇺🇸 Vault Files
        </button>
        <button type="button" onclick="launchDocQueueEpisode(${ep.id}, 'both')" class="btn-lime py-2 px-2 text-[11px] font-black">
          🌎 Ambos (BR+US)
        </button>
      </div>
    </div>
  `).join('');
}

async function launchDocQueueEpisode(episodeId, target = 'both') {
  try {
    const docAspect = document.getElementById('doc-aspect')?.value || '16:9';
    const payload = {
      episode_id: Number(episodeId),
      target,
      aspect_ratio: docAspect,
      target_minutes: Number(document.getElementById('doc-minutes')?.value || 17.0),
      caption_style: docAspect === '16:9' ? 'selective_emphasis' : 'cinema_minimal',
      auto_shorts_cascade: Boolean(document.getElementById('opt-shorts-cascade')?.checked),
      flow_mode: document.getElementById('fac-flow-mode')?.value || 'economico_pro',
      max_credits_cap: Number(document.getElementById('fac-flow-cap')?.value || 45),
      use_flow_music: Boolean(document.getElementById('opt-flow-music')?.checked),
    };
    const res = await api('/api/doc-queue/manufacture', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    const label = target === 'both' ? 'Dossiê Capital (BR) + Vault Files (US)' : (target === 'pt_br' ? 'Dossiê Capital (BR)' : 'Vault Files (US)');
    showToast(`🎞️ Episódio #${episodeId} (${res.episode.short_name}) enviado para fabricação em ${label}!`);
    selectEngineStyle('netflix_doc');
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao lançar documentário: ${e.message}`, true);
  }
}

/* -------------------- Native <dialog> light-dismiss fallback -------------------- */
(function initDialogFallbacks() {
  const dlg = document.getElementById('publish-dialog');
  if (!dlg) return;
  dlg.addEventListener('close', () => {
    dlg.returnValue = '';
  });
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    const outside = (e) => {
      const r = dlg.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    dlg.addEventListener('pointerdown', (e) => { pressedOutside = outside(e); });
    dlg.addEventListener('pointerup', (e) => { if (pressedOutside && outside(e)) dlg.close('backdrop'); });
  }
})();

/* -------------------- Live Telemetry Polling -------------------- */
async function pollTelemetry() {
  try {
    const t = await api('/api/telemetry');
    const qsEl = document.getElementById('txt-quicksync');
    const qsBadge = document.getElementById('badge-quicksync');
    if (t.quicksync_on) {
      qsEl.textContent = 'Intel QuickSync iHD ON';
      qsBadge.classList.remove('border-frimegold/60', 'text-frimegold');
      qsBadge.classList.add('border-frimelime/50', 'text-frimelime');
    } else {
      qsEl.textContent = 'CPU x264 Mode';
    }
    const tempEl = document.getElementById('txt-temp');
    tempEl.textContent = `${t.cpu_temp_c}°C`;
    tempEl.style.color = t.cpu_temp_c >= t.thermal_limit_c ? '#FF2E93' : (t.cpu_temp_c >= 75 ? '#FFD166' : '#B8FF01');
    document.getElementById('txt-cost').textContent = `$${Number(t.total_cost_usd).toFixed(4)}`;
    document.getElementById('live-queue-badge').textContent = `Fila: ${t.queue_size}`;

    if (t.flow_pro) {
      STATE.flow_pro = t.flow_pro;
      const cr = Number(t.flow_pro.credits_remaining ?? 10000).toLocaleString('pt-BR');
      const flowEl = document.getElementById('txt-flow-credits');
      if (flowEl) {
        flowEl.textContent = `🌊 Flow Pro: ${cr} cr`;
      }
    }
  } catch (e) {
    // ignore transient poll errors
  }
}

/* -------------------- Bootstrap & Render UI -------------------- */
async function refreshAll() {
  try {
    const data = await api('/api/bootstrap-data');
    STATE = { ...STATE, ...data };
    if (data.flow_pro) {
      const cr = Number(data.flow_pro.credits_remaining ?? 10000).toLocaleString('pt-BR');
      const flowEl = document.getElementById('txt-flow-credits');
      if (flowEl) flowEl.textContent = `🌊 Flow Pro: ${cr} cr`;
    }
    renderSelectors();
    renderDocQueue();
    renderPresetsGrid();
    renderClientChips();
    renderSettingsForm();
    renderRemoteAccessCard();
    renderGdriveCard();
    renderJobs();
    renderSchedules();
    renderFeedback();
  } catch (e) {
    showToast(`Erro ao carregar dados: ${e.message}`, true);
  }
}

function renderSelectors() {
  // Clients
  const cliSel = document.getElementById('fac-client');
  const prevCli = cliSel.value;
  cliSel.innerHTML = STATE.clients.map((c) => `<option value="${c.id}">${c.name} (${c.niche})</option>`).join('');
  if (prevCli && STATE.clients.some((c) => String(c.id) === String(prevCli))) {
    cliSel.value = prevCli;
  }

  // Skills
  const skSel = document.getElementById('fac-skill');
  const prevSk = skSel.value;
  skSel.innerHTML = STATE.skills.map((s) => `<option value="${s.id}">${s.name}</option>`).join('');
  if (prevSk) skSel.value = prevSk;

  // Factory Presets (#fac-preset)
  const facPresetSel = document.getElementById('fac-preset');
  if (facPresetSel) {
    const prevPreset = facPresetSel.value;
    facPresetSel.innerHTML = `<option value="">✨ Padrão do Cliente (Automático)</option>` +
      (STATE.presets || []).map((p) => `<option value="${p.id}">${p.name}${p.is_default ? ' (Padrão)' : ''}</option>`).join('');
    if (prevPreset && (STATE.presets || []).some((p) => p.id === prevPreset)) {
      facPresetSel.value = prevPreset;
    }
  }

  // Factory LUTs (#fac-lut) & Client LUTs (#cli-lut)
  const lutOptions = (STATE.luts || []).map((l) => `<option value="${l}">${l.replace('.cube', '').replaceAll('_', ' ')}</option>`).join('');
  const facLutSel = document.getElementById('fac-lut');
  if (facLutSel) {
    const prevLut = facLutSel.value;
    facLutSel.innerHTML = `<option value="">🎞️ Automática do Preset / Cliente</option>${lutOptions}`;
    if (prevLut && (STATE.luts || []).includes(prevLut)) {
      facLutSel.value = prevLut;
    }
  }
  const lutSel = document.getElementById('cli-lut');
  const prevCliLut = lutSel.value;
  lutSel.innerHTML = lutOptions;
  if (prevCliLut && (STATE.luts || []).includes(prevCliLut)) {
    lutSel.value = prevCliLut;
  }

  // Factory Music Selector (#fac-music-file)
  const musicSel = document.getElementById('fac-music-file');
  if (musicSel) {
    const prevMusic = musicSel.value || 'auto';
    const mp3Opts = (STATE.music || []).map((m) => `<option value="${m}">🎧 ${m.replace('.mp3', '').replaceAll('_', ' ')} (${m})</option>`).join('');
    musicSel.innerHTML = `
      <option value="auto">🎵 Automática do Preset / Clima do Tema</option>
      <option value="flow_vault">🌊 Flow Music Vault (Trilha Exclusiva IA)</option>
      <option value="none">🔇 Sem Trilha Musical (Voz + SFX)</option>
      ${mp3Opts ? `<optgroup label="Biblioteca Local (assets/music)">${mp3Opts}</optgroup>` : ''}
    `;
    const validMusicValues = ['auto', 'flow_vault', 'none', ...(STATE.music || [])];
    musicSel.value = validMusicValues.includes(prevMusic) ? prevMusic : 'auto';
  }

  // Factory Caption Styles (#fac-caption-style) synced from backend catalog when available
  const capSel = document.getElementById('fac-caption-style');
  if (capSel && Array.isArray(STATE.caption_styles) && STATE.caption_styles.length > 0) {
    const prevCap = capSel.value || 'hormozi_neon';
    capSel.innerHTML = STATE.caption_styles
      .map((cs) => `<option value="${cs.id}">${cs.label || cs.name || cs.id}</option>`)
      .join('');
    if (STATE.caption_styles.some((cs) => cs.id === prevCap)) {
      capSel.value = prevCap;
    }
  }

  // Voice lists synced to selected voice engines (both Tab 1 Factory & Tab 3 Clients)
  syncVoiceListForEngine();
  syncFactoryVoiceList();

  // Load first client into form if empty
  if (!document.getElementById('cli-id').value && STATE.clients.length > 0) {
    loadClientIntoForm(STATE.clients[0]);
  }

  onFactoryPresetChange();
  updateLibraryMixCount();
  updateMusicVolLabel();
  updateAdvancedSummaryPill();
  updateRecipeSummary();
}

function syncVoiceListForEngine(preferredVoiceId = null) {
  const eng = document.getElementById('cli-voice-engine').value || 'edge';
  const vSel = document.getElementById('cli-voice-id');
  const prev = preferredVoiceId || vSel.value;
  const pools = getAllVoicePools();
  const list = eng === 'gemini_tts' ? pools.gemini : (eng === 'kokoro' ? pools.kokoro : pools.edge);
  vSel.innerHTML = list.map((v) => `<option value="${v.id}">${v.name}</option>`).join('');
  if (prev && list.some((v) => v.id === prev)) {
    vSel.value = prev;
  }
}

function renderPresetsGrid() {
  const container = document.getElementById('presets-grid');
  const selectedId = document.getElementById('cli-preset-id').value || 'frimerise_signature';
  container.innerHTML = STATE.presets.map((p) => {
    const isSel = p.id === selectedId;
    return `
      <div class="preset-card ${isSel ? 'selected' : ''}" onclick="selectPreset('${p.id}')">
        <div class="flex items-center justify-between gap-2 mb-1">
          <strong class="text-sm text-white">${p.name} ${p.is_default ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-frimelime text-[#0B0713] ml-1">PADRÃO</span>' : ''}</strong>
          <div class="flex items-center gap-1">
            <span class="w-3.5 h-3.5 rounded-full inline-block" style="background:${p.primary_color}"></span>
            <span class="w-3.5 h-3.5 rounded-full inline-block" style="background:${p.secondary_color}"></span>
            <span class="w-3.5 h-3.5 rounded-full inline-block" style="background:${p.highlight_color}"></span>
            <span class="w-3.5 h-3.5 rounded-full inline-block" style="background:${p.accent_gold}"></span>
          </div>
        </div>
        <p class="text-[11px] text-[#B6A9D4] leading-snug">${p.tagline}</p>
        <div class="mt-2 flex flex-wrap gap-1.5 text-[10px] text-frimelilac">
          <span class="px-2 py-0.5 rounded bg-[#0B0713]">LUT: ${p.lut_file.replace('.cube','')}</span>
          <span class="px-2 py-0.5 rounded bg-[#0B0713]">Fonte: ${p.font_file.replace('.ttf','')}</span>
        </div>
      </div>
    `;
  }).join('');
}

function selectPreset(presetId) {
  document.getElementById('cli-preset-id').value = presetId;
  const p = STATE.presets.find((x) => x.id === presetId);
  if (p) {
    document.getElementById('cli-lut').value = p.lut_file;
    document.getElementById('cli-voice-id').value = p.voice_id;
  }
  renderPresetsGrid();
}

function renderClientChips() {
  const wrap = document.getElementById('clients-chips');
  wrap.innerHTML = STATE.clients.map((c) => {
    const isTwin = c.name === 'Dossiê Capital' || c.name === 'Vault Files';
    const flag = c.name === 'Dossiê Capital' ? '🇧🇷 ' : (c.name === 'Vault Files' ? '🇺🇸 ' : '');
    return `
      <button type="button" onclick='loadClientIntoForm(${JSON.stringify(c).replace(/'/g, "&apos;")})'
        class="btn-ghost px-3 py-1.5 text-xs font-bold flex items-center gap-2 ${isTwin ? 'border-frimegold/50' : ''}">
        <span>${flag}${c.name}</span>
        ${c.tiktok_connected ? '<span class="text-frimelime">●TT</span>' : ''}
        ${c.youtube_connected ? '<span class="text-frimegold">●YT</span>' : ''}
        ${c.facebook_connected ? '<span class="text-frimelilac">●FB</span>' : ''}
      </button>
    `;
  }).join('');
}

function loadClientIntoForm(c) {
  document.getElementById('cli-id').value = c.id || '';
  document.getElementById('cli-name').value = c.name || '';
  document.getElementById('cli-niche').value = c.niche || '';
  document.getElementById('cli-preset-id').value = c.preset_id || 'frimerise_signature';
  document.getElementById('cli-lut').value = c.lut_file || '01_frimerise_signature.cube';
  document.getElementById('cli-voice-engine').value = c.voice_engine || 'edge';
  syncVoiceListForEngine(c.voice_id || 'pt-BR-AntonioNeural');
  document.getElementById('cli-logo-path').value = c.logo_path || 'assets/brand/frimerise_logo.png';
  document.getElementById('cli-proxy').value = c.proxy_url || '';
  document.getElementById('cli-watermark').value = c.watermark_text || 'PRÉVIA • FRIMERISE';
  try {
    const b = typeof c.voice_blend === 'string' ? JSON.parse(c.voice_blend) : (c.voice_blend || {});
    document.getElementById('blend-dora').value = Math.round((b.pf_dora ?? 0.35) * 100);
    document.getElementById('blend-alex').value = Math.round((b.pm_alex ?? 0.65) * 100);
    document.getElementById('blend-santa').value = Math.round((b.pm_santa ?? 0.0) * 100);
  } catch (e) {}
  updateBlendLabels();
  renderPresetsGrid();
}

function resetClientForm() {
  loadClientIntoForm({
    id: '',
    name: '',
    niche: 'Negócio Local / UGC',
    preset_id: 'frimerise_signature',
    lut_file: '01_frimerise_signature.cube',
    voice_engine: 'edge',
    voice_id: 'pt-BR-ThalitaNeural',
    logo_path: 'assets/brand/frimerise_logo.png',
    watermark_text: 'PRÉVIA • FRIMERISE',
  });
}

function updateBlendLabels() {
  document.getElementById('lbl-dora').textContent = `${document.getElementById('blend-dora').value}%`;
  document.getElementById('lbl-alex').textContent = `${document.getElementById('blend-alex').value}%`;
  document.getElementById('lbl-santa').textContent = `${document.getElementById('blend-santa').value}%`;
}

async function uploadClientLogo(input) {
  if (!input.files || !input.files[0]) return;
  const fd = new FormData();
  fd.append('file', input.files[0]);
  try {
    const res = await fetch('/api/clients/upload-logo', { method: 'POST', body: fd });
    const data = await res.json();
    document.getElementById('cli-logo-path').value = data.logo_path;
    showToast('Logo do cliente enviada com sucesso!');
  } catch (e) {
    showToast('Falha no upload da logo.', true);
  }
}

async function previewVoice() {
  const btn = document.getElementById('btn-voice-preview');
  btn.disabled = true;
  btn.textContent = '⏳ Gerando...';
  try {
    const res = await api('/api/voice/preview', {
      method: 'POST',
      body: JSON.stringify({
        voice_engine: document.getElementById('cli-voice-engine').value,
        voice_id: document.getElementById('cli-voice-id').value,
        voice_blend: {
          pf_dora: Number(document.getElementById('blend-dora').value) / 100,
          pm_alex: Number(document.getElementById('blend-alex').value) / 100,
          pm_santa: Number(document.getElementById('blend-santa').value) / 100,
        },
      }),
    });
    const audio = document.getElementById('voice-preview-audio');
    audio.src = res.audio_url;
    audio.classList.remove('hidden');
    audio.play();
    showToast(`Prévia de voz pronta (${res.duration_s}s)!`);
  } catch (e) {
    showToast(`Erro na prévia de voz: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Ouvir Prévia';
  }
}

async function saveClient() {
  try {
    const cid = document.getElementById('cli-id').value;
    const payload = {
      id: cid ? Number(cid) : null,
      name: document.getElementById('cli-name').value.trim() || 'Novo Cliente',
      niche: document.getElementById('cli-niche').value.trim() || 'Negócios',
      preset_id: document.getElementById('cli-preset-id').value,
      lut_file: document.getElementById('cli-lut').value,
      voice_engine: document.getElementById('cli-voice-engine').value,
      voice_id: document.getElementById('cli-voice-id').value,
      voice_blend: {
        pf_dora: Number(document.getElementById('blend-dora').value) / 100,
        pm_alex: Number(document.getElementById('blend-alex').value) / 100,
        pm_santa: Number(document.getElementById('blend-santa').value) / 100,
      },
      logo_path: document.getElementById('cli-logo-path').value.trim(),
      proxy_url: document.getElementById('cli-proxy').value.trim(),
      watermark_text: document.getElementById('cli-watermark').value.trim() || 'PRÉVIA • FRIMERISE',
    };
    const res = await api('/api/clients', { method: 'POST', body: JSON.stringify(payload) });
    document.getElementById('cli-id').value = res.client.id;
    showToast(`Cliente "${res.client.name}" salvo!`);
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao salvar cliente: ${e.message}`, true);
  }
}

async function connectSocial(platform) {
  const cid = Number(document.getElementById('cli-id').value || 1);
  try {
    const res = await api(`/api/clients/${cid}/connect/${platform}`, { method: 'POST' });
    showToast(res.message);
  } catch (e) {
    showToast(`Erro Camoufox: ${e.message}`, true);
  }
}

/* -------------------- Factory Manufacture -------------------- */
document.getElementById('btn-manufacture').addEventListener('click', async () => {
  const btn = document.getElementById('btn-manufacture');
  btn.disabled = true;
  try {
    const batchLines = document.getElementById('fac-batch').value
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    const durSec = Math.max(10, Math.min(1200, Math.round(Number(document.getElementById('fac-duration-s')?.value || 30))));
    const aspectRatio = document.getElementById('fac-aspect-universal')?.value
      || (STATE.activeStyle === 'netflix_doc'
        ? (document.getElementById('doc-aspect')?.value || '16:9')
        : (document.getElementById('fac-aspect')?.value || '9:16'));

    const fpsVal = Number(document.getElementById('fac-fps-universal')?.value || document.getElementById('fac-fps')?.value || 30);
    const voiceEngineRaw = document.getElementById('fac-voice-engine')?.value || 'auto';
    const voiceIdRaw = document.getElementById('fac-voice-id')?.value || '';
    const resolvedVoice = resolveEffectiveFactoryVoice();
    const effectiveVoiceEngine = voiceEngineRaw === 'auto'
      ? (voiceIdRaw ? resolvedVoice.voice_engine : 'auto')
      : voiceEngineRaw;

    const musicFile = document.getElementById('fac-music-file')?.value || 'auto';
    const useFlowMusic = musicFile === 'flow_vault'
      || (musicFile === 'auto' && Boolean(document.getElementById('opt-flow-music')?.checked));
    const musicVol = Number(document.getElementById('fac-music-vol')?.value || 18) / 100;

    const visualLibraries = getSelectedVisualLibraries();
    const language = document.getElementById('fac-language')?.value || 'pt_br';
    const presetVal = (document.getElementById('fac-preset')?.value || '').trim();
    const lutVal = (document.getElementById('fac-lut')?.value || '').trim();
    const captionStyle = document.getElementById('fac-caption-style')?.value || 'hormozi_neon';
    const cutCadence = Number(document.getElementById('fac-cut-cadence')?.value || 3.5);
    const customDirectives = (document.getElementById('fac-custom-directives')?.value || '').trim();

    const payload = {
      client_id: Number(document.getElementById('fac-client').value || 1),
      mode: STATE.activeMode,
      engine_style: STATE.activeStyle,
      aspect_ratio: aspectRatio,
      cartoon_tone: document.getElementById('fac-tone')?.value || 'Comédia Nordestina/BR',
      cartoon_fps: fpsVal,
      cartoon_voice_engine: (effectiveVoiceEngine === 'gemini_tts' || effectiveVoiceEngine === 'edge')
        ? effectiveVoiceEngine
        : (document.getElementById('fac-cartoon-voice')?.value || 'gemini_tts'),
      clone_languages: Boolean(document.getElementById('opt-clone-langs')?.checked),
      flow_mode: document.getElementById('fac-flow-mode')?.value || 'economico_pro',
      max_credits_cap: Number(document.getElementById('fac-flow-cap')?.value || 45),
      use_flow_music: useFlowMusic,
      doc_lang: language,
      target_minutes: Number((durSec / 60).toFixed(2)),
      thumb_3words: (document.getElementById('doc-thumb-hook')?.value || '').trim() || null,
      auto_shorts_cascade: Boolean(document.getElementById('opt-shorts-cascade')?.checked),
      topic: document.getElementById('fac-topic').value.trim(),
      batch_topics: batchLines,
      source_url: document.getElementById('fac-url').value.trim(),
      reference_mp4_path: document.getElementById('fac-ref-mp4-path').value.trim(),
      skill_id: document.getElementById('fac-skill').value,
      preset_id: presetVal || null,
      lut_file: lutVal || null,
      motion_cards: visualLibraries.length > 0
        ? visualLibraries.includes('skia_graphics')
        : Boolean(document.getElementById('opt-motion').checked),
      seamless_loop: document.getElementById('opt-loop').checked,
      dual_hook_ab: document.getElementById('opt-ab').checked,
      // Full Estúdio de Criação Personalizada overrides
      voice_engine: effectiveVoiceEngine,
      voice_id: voiceIdRaw || null,
      voice_rate: document.getElementById('fac-voice-rate')?.value || '+8%',
      voice_pitch: document.getElementById('fac-voice-pitch')?.value || '+0Hz',
      target_duration_s: durSec,
      cut_cadence_s: cutCadence,
      fps: fpsVal,
      music_file: musicFile,
      music_volume: Number(musicVol.toFixed(2)),
      caption_style: captionStyle,
      language: language,
      visual_libraries: visualLibraries,
      custom_directives: customDirectives,
    };
    const res = await api('/api/factory/manufacture', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast(`🚀 ${res.count} vídeo(s) enviado(s) para a fábrica FrimeRise (${STATE.activeStyle} • ${aspectRatio} • ${durSec}s • ${visualLibraries.length} libs)!`);
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao enfileirar: ${e.message}`, true);
  } finally {
    btn.disabled = false;
  }
});

/* -------------------- Jobs & VIP Delivery Center -------------------- */
function renderJobs() {
  const jobs = STATE.jobs || [];
  const active = jobs.find((j) => j.status === 'running' || j.status === 'queued') || jobs[0];
  if (active) {
    document.getElementById('active-job-title').textContent = active.topic;
    document.getElementById('active-job-pct').textContent = `${active.progress}%`;
    document.getElementById('active-job-bar').style.width = `${active.progress}%`;
    document.getElementById('active-job-stage').textContent = `${active.status.toUpperCase()} • ${active.stage}`;
    const logEl = document.getElementById('active-job-log');
    logEl.textContent = active.log || 'Na fila de fabricação...';
    logEl.scrollTop = logEl.scrollHeight;
  }

  const listEl = document.getElementById('recent-jobs-list');
  if (!jobs.length) {
    listEl.innerHTML = '<div class="text-xs text-[#B6A9D4]">Nenhuma produção ainda. Clique em Fabricar Vídeo ou lance um Documentário da Fila Pronta acima!</div>';
  } else {
    listEl.innerHTML = jobs.slice(0, 9).map((j) => {
      const badgeColor = j.status === 'completed' ? 'text-frimelime border-frimelime/40 bg-frimelime/10'
        : j.status === 'error' ? 'text-frimepink border-frimepink/40 bg-frimepink/10'
        : 'text-frimegold border-frimegold/40 bg-frimegold/10';
      const eng = (j.quality_report && j.quality_report.engine_style) || '';
      const engTag = eng === 'netflix_doc' ? '🎞️ Doc Cinema' : (eng === 'cartoon_2d' ? '🎭 Cartoon 2D' : '🎬 Viral 2.5D');
      const gd = j.gdrive_backup || (j.quality_report && j.quality_report.gdrive_backup) || {};
      const driveBadge = gd.status === 'uploaded'
        ? (j.drive_url
            ? `<a href="${j.drive_url}" target="_blank" rel="noopener" class="text-[10px] font-bold text-frimelime underline">☁️ Drive ↗</a>`
            : `<span class="text-[10px] font-bold text-frimelime">☁️ No Drive</span>`)
        : '';
      const actionHtml = j.status === 'completed'
        ? `<button type="button" onclick="openInVip('${j.id}')" class="btn-gold w-full py-1.5 text-[11px]">👑 Abrir na Central VIP</button>`
        : (j.status === 'error'
            ? `<div class="flex gap-2">
                 <button type="button" onclick="resumeJob('${j.id}')" class="btn-lime flex-1 py-1.5 text-[11px] font-black">♻️ Retomar Job</button>
                 <button type="button" onclick="openInVip('${j.id}')" class="btn-ghost px-2.5 py-1.5 text-[11px]">Logs</button>
               </div>`
            : `<div class="lime-progress-track"><div class="lime-progress-fill" style="width:${j.progress}%"></div></div>`);
      return `
        <div class="p-3.5 rounded-xl bg-[#0B0713]/85 border border-[rgba(179,136,255,0.2)] space-y-2">
          <div class="flex items-start justify-between gap-2">
            <strong class="text-xs text-white line-clamp-2">${j.topic}</strong>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border ${badgeColor} shrink-0">${j.status}</span>
          </div>
          <div class="flex items-center justify-between text-[11px] text-[#B6A9D4]">
            <span>${j.client_name || 'FrimeRise'} • ${engTag} • ${j.duration_s || 0}s</span>
            <span class="flex items-center gap-2">${driveBadge}<span class="text-frimegold font-bold">${j.views_count || 0} views</span></span>
          </div>
          ${actionHtml}
        </div>
      `;
    }).join('');
  }

  const completed = jobs.filter((j) => j.status === 'completed');
  const vipSel = document.getElementById('vip-job-select');
  const pubSel = document.getElementById('pub-job');
  const fbSel = document.getElementById('fb-job');
  const optsHtml = completed.map((j) => `<option value="${j.id}">${j.topic.slice(0, 52)} (${j.duration_s}s)</option>`).join('');
  vipSel.innerHTML = optsHtml || '<option value="">Nenhum vídeo finalizado ainda</option>';
  pubSel.innerHTML = optsHtml;
  fbSel.innerHTML = optsHtml;

  if (completed.length > 0) {
    if (!STATE.selectedVipJobId || !completed.some((x) => x.id === STATE.selectedVipJobId)) {
      STATE.selectedVipJobId = completed[0].id;
    }
    vipSel.value = STATE.selectedVipJobId;
    renderVipJob(STATE.selectedVipJobId);
  }
}

document.getElementById('vip-job-select').addEventListener('change', (e) => {
  STATE.selectedVipJobId = e.target.value;
  renderVipJob(STATE.selectedVipJobId);
});

function openInVip(jobId) {
  STATE.selectedVipJobId = jobId;
  document.querySelector('.nav-tab[data-tab="vip"]').click();
  document.getElementById('vip-job-select').value = jobId;
  renderVipJob(jobId);
}

async function resumeJob(jobId) {
  try {
    await api(`/api/jobs/${jobId}/resume`, { method: 'POST' });
    showToast(`♻️ Job ${jobId} recolocado na fila de retomada!`);
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao retomar job: ${e.message}`, true);
  }
}

async function uploadVipJobToGdrive() {
  const jobId = STATE.selectedVipJobId;
  if (!jobId) return showToast('Selecione um vídeo primeiro.', true);
  const btn = document.getElementById('btn-vip-gdrive-upload');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Enviando ao Drive...';
  }
  try {
    const res = await api(`/api/jobs/${jobId}/gdrive-upload`, { method: 'POST' });
    if (res.status === 'uploaded') {
      showToast(`☁️ Enviado ao Google Drive (${res.files_uploaded || 0} arquivos • ${res.total_mb || 0} MB)!`);
    } else {
      showToast(`Google Drive: ${res.detail || res.status}`, true);
    }
    await refreshAll();
  } catch (e) {
    showToast(`Erro no upload Drive: ${e.message}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '☁️ Enviar ao Google Drive';
    }
  }
}

function renderVipJob(jobId) {
  const job = STATE.jobs.find((j) => j.id === jobId);
  if (!job) return;

  const avail = job.artifacts_available || {};
  const qr = job.quality_report || {};
  const gd = job.gdrive_backup || qr.gdrive_backup || {};
  const driveUrl = job.drive_url || gd.drive_url || '';

  const pA = document.getElementById('player-hook-a');
  const pB = document.getElementById('player-hook-b');
  // Use real master if still on SSD, otherwise fall back cleanly to 540p preview for browser playback (never blank!)
  const srcA = (avail.master && job.master_path)
    ? `/${job.master_path}`
    : (job.hook_a_path && !job.hook_a_path.endsWith('preview_540p.mp4')
        ? `/${job.hook_a_path}`
        : (job.preview_path ? `/${job.preview_path}` : ''));
  const srcB = (avail.hook_b && job.hook_b_path) ? `/${job.hook_b_path}` : srcA;

  if (pA.getAttribute('data-src') !== srcA) {
    pA.setAttribute('data-src', srcA);
    pA.src = srcA;
  }
  if (pB.getAttribute('data-src') !== srcB) {
    pB.setAttribute('data-src', srcB);
    pB.src = srcB;
  }

  const _bindDl = (id, url, isAvailable, fallbackText = null) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (isAvailable) {
      el.href = url;
      el.classList.remove('opacity-40', 'pointer-events-none');
      el.removeAttribute('aria-disabled');
      el.removeAttribute('title');
    } else {
      el.href = '#';
      el.classList.add('opacity-40', 'pointer-events-none');
      el.setAttribute('aria-disabled', 'true');
      if (fallbackText) el.title = fallbackText;
    }
  };

  const drivePrunedNote = gd.status === 'uploaded' ? 'Arquivado no Google Drive (podado do SSD local)' : 'Artefato indisponível no SSD';
  _bindDl('dl-master', `/api/download/${job.id}/master`, Boolean(avail.master ?? job.master_path), drivePrunedNote);
  _bindDl('dl-capcut', `/api/download/${job.id}/capcut`, Boolean(avail.capcut ?? job.capcut_zip_path), drivePrunedNote);
  _bindDl('dl-preview', `/api/download/${job.id}/preview`, Boolean(avail.preview ?? job.preview_path), 'Prévia 540p indisponível');
  _bindDl('dl-otio', `/api/download/${job.id}/otio`, Boolean(avail.otio ?? job.otio_path), 'Timeline OTIO indisponível');
  _bindDl('dl-cover', `/api/download/${job.id}/cover`, Boolean(avail.cover ?? job.cover_path), 'Capa HD indisponível');
  _bindDl('dl-hookb', `/api/download/${job.id}/hook_b`, Boolean(avail.hook_b ?? job.hook_b_path), 'Sem versão B neste job');
  _bindDl('dl-edl', `/api/download/${job.id}/edl`, Boolean(avail.edl), 'EDL não gerado para este motor');
  _bindDl('dl-script', `/api/download/${job.id}/script`, Boolean(avail.script ?? true), 'Roteiro indisponível');
  _bindDl('dl-qc', `/api/download/${job.id}/qc`, Boolean(avail.qc), 'QC Broadcast não disponível');
  _bindDl('dl-tiktok', `/api/download/${job.id}/tiktok`, Boolean(avail.tiktok), drivePrunedNote);
  _bindDl('dl-reels', `/api/download/${job.id}/reels`, Boolean(avail.reels), drivePrunedNote);
  _bindDl('dl-shorts', `/api/download/${job.id}/shorts`, Boolean(avail.shorts), drivePrunedNote);

  const driveLinkEl = document.getElementById('vip-drive-link');
  const driveStatusEl = document.getElementById('vip-drive-status');
  if (driveLinkEl) {
    if (driveUrl) {
      driveLinkEl.href = driveUrl;
      driveLinkEl.classList.remove('hidden');
    } else {
      driveLinkEl.classList.add('hidden');
    }
  }
  if (driveStatusEl) {
    if (gd.status === 'uploaded') {
      const prunedTag = gd.pruned_local ? ' • SSD podado (Prévia 540p local)' : ' • Cópia local mantida';
      const pathLbl = gd.remote_path ? `<code>${gd.remote_path}</code>` : 'Google Drive';
      driveStatusEl.innerHTML = `<span class="text-frimelime font-bold">☁️ Salvo no Google Drive</span> (${pathLbl}${prunedTag})`;
    } else if (gd.status === 'error') {
      driveStatusEl.innerHTML = `<span class="text-frimepink font-bold">⚠️ Erro Drive:</span> ${gd.detail || 'falha no envio'}`;
    } else {
      driveStatusEl.textContent = '☁️ Google Drive: ainda não enviado (Master local no SSD)';
    }
  }

  if (job.cover_path) {
    document.getElementById('vip-cover-img').src = `/${job.cover_path}`;
  }
  const cc = qr.creative_config || {};
  const qc = job.qc_report || qr.qc_summary || {};
  const qcBadge = qc.metrics
    ? ` • QC: <span class="${qc.passed ? 'text-frimelime' : 'text-frimepink'} font-bold">${qc.passed ? 'PASS' : 'FAIL'}${qc.metrics.integrated_lufs ? ` (${qc.metrics.integrated_lufs} LUFS / ${qc.metrics.true_peak_dbtp ?? '?'} dBTP)` : ''}</span>`
    : '';
  const ccMix = Array.isArray(cc.visual_libraries) && cc.visual_libraries.length
    ? ` • 🧩 Mix: <span class="text-white font-semibold">${cc.visual_libraries.join(', ')}</span>`
    : '';
  const ccVoice = cc.voice_id
    ? ` • 🎙️ <span class="text-frimepink font-semibold">${cc.voice_id}</span> (${cc.voice_rate || '+8%'})`
    : '';
  document.getElementById('vip-job-meta').innerHTML = `
    <strong class="text-white block text-sm mb-1">${job.topic}</strong>
    Motor: <span class="text-frimepink font-bold">${qr.engine_style || 'cinematic_broll'}</span> • Duração: <span class="text-frimelime font-bold">${job.duration_s}s</span> • Formato: <span class="text-frimelilac font-bold">${qr.aspect_ratio || '9:16'}</span> • Custo: <span class="text-frimegold font-bold">$${Number(job.cost_usd || 0).toFixed(5)}</span>${qcBadge}${ccVoice}${ccMix}
  `;

  const ra = qr.retention_audit || {};
  const retBadge = document.getElementById('vip-retention-badge');
  if (retBadge) {
    retBadge.textContent = `🩺 Retention Doctor: ${ra.open_loops_total ?? 1} Open Loop(s) ativos (15-25s) • ${ra.cliches_blocked ?? 0} clichês robóticos bloqueados`;
  }

  // 1. Render 3 A/B/C 1280x720 Thumbnails
  const thumbsGrid = document.getElementById('vip-thumbs-grid');
  const thumbs = qr.ab_thumbnails || {};
  if (thumbsGrid) {
    if (thumbs.thumb_a && thumbs.thumb_b && thumbs.thumb_c) {
      const items = [
        { label: 'A • Mystery / True Crime', path: thumbs.thumb_a, border: 'border-frimepink/50' },
        { label: 'B • Neon Split Contrast', path: thumbs.thumb_b, border: 'border-frimelime/50' },
        { label: 'C • Extreme Focal Zoom', path: thumbs.thumb_c, border: 'border-frimegold/50' },
      ];
      thumbsGrid.innerHTML = items.map((it) => `
        <a href="/${it.path}" download class="block p-2 rounded-xl bg-[#140E24] border ${it.border} hover:scale-[1.02] transition no-underline space-y-1.5">
          <img src="/${it.path}?t=${Date.now()}" alt="${it.label}" class="w-full aspect-video object-cover rounded-lg bg-black" />
          <div class="flex items-center justify-between text-[11px] font-bold text-white px-1">
            <span>${it.label}</span><span class="text-frimelime">1280×720 ↓</span>
          </div>
        </a>
      `).join('');
    } else {
      thumbsGrid.innerHTML = '<div class="text-xs text-[#B6A9D4] sm:col-span-3">Clique em <strong>"🖼️ Gerar 3 Thumbnails A/B (1280×720)"</strong> acima para criar o Trio A/B/C com Skia C++ + rembg (u2netp).</div>';
    }
  }

  // 2. Render 5 Extracted 9:16 Viral Shorts Cascade
  const shortsList = document.getElementById('vip-shorts-list');
  const shorts = qr.shorts_cascade || [];
  if (shortsList) {
    if (shorts.length > 0) {
      shortsList.innerHTML = shorts.map((s) => {
        const relUrl = s.url || ('/' + String(s.path || '').replace(/^.*outputs\//, 'outputs/'));
        return `
          <a href="${relUrl}" download class="btn-ghost px-3 py-2 text-xs font-bold flex items-center justify-between no-underline border-frimelime/40">
            <span>📱 Corte #${s.short_idx} (${s.duration_s}s • 9:16)</span><span class="text-frimelime">MP4 ↓</span>
          </a>
        `;
      }).join('');
    } else {
      shortsList.innerHTML = '<div class="text-[11px] text-[#B6A9D4] sm:col-span-2">Nenhum corte extraído ainda. Clique em <strong>"⚡ Extrair 5 Cortes Virais 9:16"</strong> acima!</div>';
    }
  }

  // 3. Render Multi-Language Dubbed Versions (EN-US + ES)
  const dubsList = document.getElementById('vip-dubs-list');
  const dubs = qr.dubbed_languages || {};
  if (dubsList) {
    const entries = Object.entries(dubs);
    if (entries.length > 0) {
      dubsList.innerHTML = entries.map(([code, info]) => `
        <a href="/${info.path}" download class="btn-gold px-3 py-1.5 text-xs flex items-center gap-2 no-underline">
          <span>🌎 ${info.language} (${info.duration_s}s)</span><span>MP4 ↓</span>
        </a>
      `).join('');
    } else {
      dubsList.innerHTML = '<span class="text-[11px] text-[#B6A9D4]">Clique em "🌎 Clonar EN-US + ES Agora" para dublar com Re-Timing e Lip-Sync 2D.</span>';
    }
  }
}

async function generateVipThumbnails() {
  const jobId = STATE.selectedVipJobId;
  if (!jobId) return showToast('Selecione um vídeo primeiro.', true);
  const btn = document.getElementById('btn-gen-thumbs');
  btn.disabled = true;
  btn.textContent = '⏳ Recortando (u2netp) & Renderizando...';
  try {
    await api(`/api/jobs/${jobId}/generate-thumbnails`, { method: 'POST' });
    showToast('🖼️ 3 Thumbnails Magnéticas 1280×720 (A/B/C) geradas com sucesso!');
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao gerar thumbnails: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '🖼️ Gerar 3 Thumbnails A/B (1280×720)';
  }
}

async function extract5ViralShorts() {
  const jobId = STATE.selectedVipJobId;
  if (!jobId) return showToast('Selecione um vídeo primeiro.', true);
  const btn = document.getElementById('btn-extract-shorts');
  btn.disabled = true;
  btn.textContent = '⏳ Extraindo 5 Cortes 9:16 (MediaPipe + Skia)...';
  try {
    const res = await api(`/api/jobs/${jobId}/extract-shorts`, { method: 'POST' });
    showToast(`⚡ ${res.count} Cortes Virais 9:16 extraídos com sucesso (Zero Tokens)!`);
    await refreshAll();
  } catch (e) {
    showToast(`Erro na cascata 9:16: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Extrair 5 Cortes Virais 9:16 (Zero Tokens)';
  }
}

async function dubVipJobLanguages() {
  const jobId = STATE.selectedVipJobId;
  if (!jobId) return showToast('Selecione um vídeo primeiro.', true);
  const btn = document.getElementById('btn-dub-langs');
  btn.disabled = true;
  btn.textContent = '⏳ Dublando EN-US + ES...';
  try {
    await api(`/api/jobs/${jobId}/dub-languages`, { method: 'POST' });
    showToast('🌎 Vídeos em Inglês (US) e Espanhol dublados e re-sincronizados!');
    await refreshAll();
  } catch (e) {
    showToast(`Erro na dublagem: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '🌎 Clonar EN-US + ES Agora';
  }
}

async function generateB2BProspect() {
  const btn = document.getElementById('btn-b2b-generate');
  btn.disabled = true;
  btn.textContent = '⏳ Gerando Vídeo 540p + Abordagem B2B...';
  try {
    const payload = {
      client_id: Number(document.getElementById('fac-client')?.value || 1),
      company_name: document.getElementById('b2b-company').value.trim() || 'Clínica Prime',
      city: document.getElementById('b2b-city').value.trim() || 'Fortaleza',
      product_service: document.getElementById('b2b-product').value.trim() || 'Atendimento VIP',
      engine_style: document.getElementById('b2b-style').value || 'cinematic_broll',
    };
    const res = await api('/api/b2b/prospect', { method: 'POST', body: JSON.stringify(payload) });
    document.getElementById('b2b-pitch-text').value = res.whatsapp_pitch;
    document.getElementById('b2b-result-box').innerHTML = `
      ✅ <strong>Job B2B #${res.job.id} iniciado!</strong> Marca d'água diagonal <code class="text-frimepink">PRÉVIA EXCLUSIVA • FRIMERISE</code> configurada.<br/>
      🩺 <strong>Retention Doctor:</strong> ${res.retention_audit?.open_loops_total ?? 1} Open Loop(s) ativos • 0 clichês robóticos.
    `;
    showToast('💼 Prospecção B2B enviada para fabricação + Pitch WhatsApp pronto!');
    await refreshAll();
  } catch (e) {
    showToast(`Erro B2B: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ GERAR PRÉVIA 540p + SCRIPT DE ABORDAGEM WHATSAPP';
  }
}

/* -------------------- Accessible Copy Button (Invoker Commands + Fallback) -------------------- */
const copyTimers = new WeakMap();
let lastCopyMessage = '';

function legacyCopyFallback(text) {
  const field = Object.assign(document.createElement('textarea'), { value: text });
  field.setAttribute('readonly', '');
  field.style.cssText = 'position:fixed;inset-block-start:0;opacity:0';
  document.body.append(field);
  field.select();
  try {
    return document.execCommand('copy');
  } finally {
    field.remove();
  }
}

function reportCopyStatus(button, ok) {
  const tip = button.nextElementSibling;
  if (!tip) return;
  clearTimeout(copyTimers.get(button));
  button.removeAttribute('data-copied');
  button.removeAttribute('data-failed');
  let message = ok ? 'Copiado!' : 'Falha ao copiar';
  if (message === lastCopyMessage) message += '\u00A0';
  lastCopyMessage = message;
  tip.textContent = '';
  void button.offsetWidth;
  button.setAttribute(ok ? 'data-copied' : 'data-failed', '');
  requestAnimationFrame(() => {
    tip.textContent = message;
  });
  copyTimers.set(
    button,
    setTimeout(() => {
      button.removeAttribute('data-copied');
      button.removeAttribute('data-failed');
      tip.textContent = '';
    }, 2200)
  );
}

async function copyTargetText(button, target) {
  const text = target.matches('input, textarea') ? target.value : target.innerText.trim();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    reportCopyStatus(button, true);
  } catch {
    const ok = legacyCopyFallback(text);
    reportCopyStatus(button, ok);
  }
}

document.addEventListener(
  'command',
  (event) => {
    if (event.command && event.command.startsWith('--copy')) {
      copyTargetText(event.source, event.target);
    }
  },
  true
);

if (!('CommandEvent' in window)) {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('button[command^="--copy"]');
    if (!button) return;
    const target = document.getElementById(button.getAttribute('commandfor'));
    if (target) copyTargetText(button, target);
  });
}

/* -------------------- Setup 1-Clique -------------------- */
function renderSettingsForm() {
  const s = STATE.settings || {};
  document.getElementById('set-gemini').value = s.gemini_api_key || '';
  document.getElementById('set-deepseek').value = s.deepseek_api_key || '';
  document.getElementById('set-pexels').value = s.pexels_api_key || '';
  document.getElementById('set-pixabay').value = s.pixabay_api_key || '';
  const llmAliases = {
    'gemini-3.5-flash-lite': 'gemini-2.5-flash-lite',
    'gemini-3.8-flash': 'gemini-2.5-flash',
  };
  const normLlm = llmAliases[s.default_llm] || s.default_llm || 'gemini-2.5-flash-lite';
  document.getElementById('set-llm').value = normLlm;
  document.getElementById('set-ollama').value = s.ollama_url || 'http://localhost:11434';
  document.getElementById('set-thermal').value = s.thermal_limit_c || '85';
}

/* -------------------- Remote Access & Tailscale Security -------------------- */
function renderRemoteAccessCard() {
  const auth = STATE.auth_status || {};
  const ts = STATE.tailscale || {};
  const s = STATE.settings || {};

  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn) {
    if (auth.authenticated || auth.auth_required) {
      logoutBtn.classList.remove('hidden');
    } else {
      logoutBtn.classList.add('hidden');
    }
  }

  const userInput = document.getElementById('auth-username');
  if (userInput && document.activeElement !== userInput) {
    userInput.value = auth.username || s.auth_username || 'frimerise';
  }
  const reqLocal = document.getElementById('auth-require-local');
  if (reqLocal) {
    reqLocal.checked = Boolean(auth.auth_require_local ?? s.auth_require_local);
  }

  const pill = document.getElementById('ts-status-pill');
  const linkEl = document.getElementById('ts-https-link');
  const hintEl = document.getElementById('ts-setup-hint');
  const detailEl = document.getElementById('ts-status-detail');
  if (!pill || !linkEl || !hintEl || !detailEl) return;

  if (ts.connected && ts.https_url) {
    pill.textContent = ts.serve_configured ? '🟢 Tailscale HTTPS Ativo' : '🟡 Tailscale Conectado';
    pill.className = ts.serve_configured
      ? 'text-[11px] font-extrabold px-3 py-1 rounded-full bg-frimelime/15 text-frimelime border border-frimelime/50'
      : 'text-[11px] font-extrabold px-3 py-1 rounded-full bg-frimegold/15 text-frimegold border border-frimegold/40';
    linkEl.href = ts.https_url;
    linkEl.textContent = ts.https_url;
    linkEl.classList.remove('hidden');
    hintEl.classList.add('hidden');
    detailEl.textContent = ts.serve_configured
      ? `IP Tailscale: ${ts.tailscale_ip}. Abra o link HTTPS acima no celular com o app Tailscale ativo (funciona no 4G/5G ou outro Wi-Fi).`
      : `Tailscale conectado (${ts.tailscale_ip}). Rode ./setup_tailscale.sh para ligar o proxy HTTPS privado na porta 8000.`;
  } else if (ts.installed) {
    pill.textContent = '🟡 Tailscale Instalado (Aguardando Login)';
    pill.className = 'text-[11px] font-extrabold px-3 py-1 rounded-full bg-frimegold/15 text-frimegold border border-frimegold/40';
    linkEl.classList.add('hidden');
    hintEl.classList.remove('hidden');
    hintEl.textContent = './setup_tailscale.sh';
    detailEl.textContent = 'Rode ./setup_tailscale.sh no terminal deste notebook para autenticar sua conta Tailscale e ativar o link privado.';
  } else {
    pill.textContent = '⚪ Pronto p/ Instalar Tailscale';
    pill.className = 'text-[11px] font-extrabold px-3 py-1 rounded-full bg-frimelilac/15 text-frimelilac border border-frimelilac/40';
    linkEl.classList.add('hidden');
    hintEl.classList.remove('hidden');
    hintEl.textContent = './setup_tailscale.sh';
    detailEl.textContent = 'Servidor já blindado (/data fechado + login ativo para acessos remotos). Execute ./setup_tailscale.sh no terminal deste notebook para conectar ao celular.';
  }
}

async function logoutSession() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (e) {}
  window.location.href = '/login';
}

function initRemoteAccessControls() {
  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      logoutSession();
    });
  }

  const toggleBtn = document.getElementById('btn-toggle-new-pwd');
  const pwdInput = document.getElementById('auth-new-password');
  if (toggleBtn && pwdInput) {
    toggleBtn.addEventListener('click', () => {
      const showing = pwdInput.type === 'text';
      pwdInput.type = showing ? 'password' : 'text';
      toggleBtn.setAttribute('aria-pressed', showing ? 'false' : 'true');
      toggleBtn.setAttribute('aria-label', showing ? 'Mostrar nova senha' : 'Ocultar nova senha');
      toggleBtn.textContent = showing ? 'Mostrar' : 'Ocultar';
    });
  }

  const form = document.getElementById('remote-auth-form');
  const submitBtn = document.getElementById('btn-save-remote-auth');
  const statusEl = document.getElementById('remote-auth-status');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const username = (document.getElementById('auth-username')?.value || '').trim();
      const newPassword = document.getElementById('auth-new-password')?.value || '';
      const requireLocal = Boolean(document.getElementById('auth-require-local')?.checked);

      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await api('/api/auth/credentials', {
          method: 'POST',
          body: JSON.stringify({
            username,
            new_password: newPassword || null,
            require_local: requireLocal,
          }),
        });
        if (pwdInput) pwdInput.value = '';
        if (statusEl) {
          statusEl.textContent = res.password_rotated
            ? '✅ Usuário e nova senha salvos (hash PBKDF2-SHA256). Sessões antigas foram revogadas.'
            : '✅ Preferências de acesso remoto salvas com sucesso.';
          statusEl.classList.remove('hidden');
        }
        showToast('🔐 Credenciais de acesso remoto atualizadas!');
        await refreshAll();
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = `❌ ${err.message}`;
          statusEl.classList.remove('hidden');
        }
        showToast(`Erro ao salvar credenciais: ${err.message}`, true);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  const gdForm = document.getElementById('gdrive-settings-form');
  const gdBtn = document.getElementById('btn-save-gdrive');
  if (gdForm) {
    gdForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (gdBtn) gdBtn.disabled = true;
      try {
        await api('/api/settings', {
          method: 'POST',
          body: JSON.stringify({
            gdrive_root_folder: (document.getElementById('gdrive-root-folder')?.value || 'FrimeRise').trim() || 'FrimeRise',
            gdrive_local_dir: (document.getElementById('gdrive-local-dir')?.value || '').trim(),
            gdrive_auto_upload: document.getElementById('gdrive-auto-upload')?.checked ? '1' : '0',
            gdrive_prune_local: document.getElementById('gdrive-prune-local')?.checked ? '1' : '0',
          }),
        });
        showToast('☁️ Preferências do Google Drive salvas!');
        await refreshAll();
      } catch (err) {
        showToast(`Erro ao salvar Google Drive: ${err.message}`, true);
      } finally {
        if (gdBtn) gdBtn.disabled = false;
      }
    });
  }
}

function renderGdriveCard() {
  const gd = STATE.gdrive || {};
  const s = STATE.settings || {};
  const pill = document.getElementById('gdrive-status-pill');
  const detail = document.getElementById('gdrive-status-detail');
  const rootIn = document.getElementById('gdrive-root-folder');
  const dirIn = document.getElementById('gdrive-local-dir');
  const autoCb = document.getElementById('gdrive-auto-upload');
  const pruneCb = document.getElementById('gdrive-prune-local');

  if (rootIn && document.activeElement !== rootIn) {
    rootIn.value = s.gdrive_root_folder || gd.root_folder || 'FrimeRise';
  }
  if (dirIn && document.activeElement !== dirIn) {
    dirIn.value = s.gdrive_local_dir || gd.local_sync_dir || '';
  }
  if (autoCb) autoCb.checked = (s.gdrive_auto_upload ?? '1') === '1';
  if (pruneCb) pruneCb.checked = (s.gdrive_prune_local ?? '1') === '1';

  if (pill && detail) {
    if (gd.connected) {
      pill.textContent = `🟢 Drive Conectado (${gd.backend})`;
      pill.className = 'text-[11px] font-extrabold px-3 py-1 rounded-full bg-frimelime/15 text-frimelime border border-frimelime/50';
      detail.textContent = gd.detail || 'Pronto para salvar cada projeto em pasta separada no Google Drive.';
    } else {
      pill.textContent = '⚪ Aguardando Conexão Drive';
      pill.className = 'text-[11px] font-extrabold px-3 py-1 rounded-full bg-frimegold/15 text-frimegold border border-frimegold/40';
      detail.textContent = gd.detail || 'Execute ./setup_gdrive.sh no terminal para conectar seu Google Drive.';
    }
  }
}

async function saveSettingsForm() {
  try {
    await api('/api/settings', {
      method: 'POST',
      body: JSON.stringify({
        gemini_api_key: document.getElementById('set-gemini').value.trim(),
        deepseek_api_key: document.getElementById('set-deepseek').value.trim(),
        pexels_api_key: document.getElementById('set-pexels').value.trim(),
        pixabay_api_key: document.getElementById('set-pixabay').value.trim(),
        default_llm: document.getElementById('set-llm').value,
        ollama_url: document.getElementById('set-ollama').value.trim(),
        thermal_limit_c: document.getElementById('set-thermal').value.trim(),
      }),
    });
    showToast('✅ Chaves e configurações salvas em data/frimerise.db!');
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao salvar: ${e.message}`, true);
  }
}

async function testSetup() {
  try {
    const res = await api('/api/settings/test', { method: 'POST' });
    const box = document.getElementById('setup-test-results');
    box.classList.remove('hidden');
    box.innerHTML = Object.entries(res.checks).map(([k, v]) => `
      <div class="p-3 rounded-xl bg-[#0B0713] border ${v.ok ? 'border-frimelime/50' : 'border-frimegold/40'}">
        <div class="font-extrabold uppercase ${v.ok ? 'text-frimelime' : 'text-frimegold'}">${v.ok ? '✔' : '●'} ${k}</div>
        <div class="text-[11px] text-[#B6A9D4] mt-0.5">${v.detail}</div>
      </div>
    `).join('');
    showToast('Diagnóstico de hardware e APIs concluído!');
  } catch (e) {
    showToast(`Erro no teste: ${e.message}`, true);
  }
}

/* -------------------- Publish / Schedule / Feedback -------------------- */
function openPublishModal(platform) {
  const dlg = document.getElementById('publish-dialog');
  document.getElementById('pub-platform').value = platform;
  if (STATE.selectedVipJobId) {
    document.getElementById('pub-job').value = STATE.selectedVipJobId;
    const j = STATE.jobs.find((x) => x.id === STATE.selectedVipJobId);
    if (j) document.getElementById('pub-caption').value = `${j.topic} #frimerise #viral #shorts`;
  }
  dlg.showModal();
}

async function submitPublishNow() {
  const dlg = document.getElementById('publish-dialog');
  try {
    const res = await api('/api/publish/now', {
      method: 'POST',
      body: JSON.stringify({
        job_id: document.getElementById('pub-job').value,
        client_id: Number(document.getElementById('fac-client').value || 1),
        platform: document.getElementById('pub-platform').value,
        caption: document.getElementById('pub-caption').value,
      }),
    });
    dlg.close('publish');
    showToast(res.message);
  } catch (e) {
    showToast(`Erro ao publicar: ${e.message}`, true);
  }
}

async function submitSchedule() {
  const dlg = document.getElementById('publish-dialog');
  try {
    const dt = document.getElementById('pub-schedule').value;
    if (!dt) {
      showToast('Escolha data e hora (BRT) para agendar.', true);
      return;
    }
    await api('/api/schedules', {
      method: 'POST',
      body: JSON.stringify({
        job_id: document.getElementById('pub-job').value,
        client_id: Number(document.getElementById('fac-client').value || 1),
        platform: document.getElementById('pub-platform').value,
        caption: document.getElementById('pub-caption').value,
        scheduled_brt: dt,
      }),
    });
    dlg.close('schedule');
    showToast('📅 Agendado no Piloto Automático com sucesso!');
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao agendar: ${e.message}`, true);
  }
}

function renderSchedules() {
  const el = document.getElementById('schedules-list');
  if (!STATE.schedules.length) {
    el.innerHTML = '<div class="text-xs text-[#B6A9D4] p-4 rounded-xl bg-[#0B0713]/60 border border-[rgba(179,136,255,0.14)]">Nenhum agendamento ainda. Use o botão "+ Agendar Post" ou a Central VIP.</div>';
    return;
  }
  el.innerHTML = STATE.schedules.map((s) => `
    <div class="p-3.5 rounded-xl bg-[#0B0713]/85 border border-[rgba(179,136,255,0.2)] flex flex-wrap items-center justify-between gap-3 text-xs">
      <div>
        <div class="font-bold text-white">${s.topic || s.job_id} <span class="text-frimepink uppercase ml-1">[${s.platform}]</span></div>
        <div class="text-[11px] text-[#B6A9D4]">BRT: <strong class="text-frimelime">${s.scheduled_brt}</strong> ${s.platform === 'facebook' ? `→ Asia/Shanghai: <strong class="text-frimegold">${s.scheduled_target_tz}</strong>` : ''}</div>
      </div>
      <span class="px-2.5 py-1 rounded-full bg-frimelilac/15 text-frimelilac font-bold uppercase text-[10px]">${s.status}</span>
    </div>
  `).join('');
}

async function submitFeedback() {
  try {
    await api('/api/feedback', {
      method: 'POST',
      body: JSON.stringify({
        job_id: document.getElementById('fb-job').value,
        platform: document.getElementById('fb-platform').value,
        hook_variant: document.getElementById('fb-variant').value,
        views: Number(document.getElementById('fb-views').value || 0),
        likes: Number(document.getElementById('fb-likes').value || 0),
        retention_pct: Number(document.getElementById('fb-ret').value || 0),
      }),
    });
    showToast('★ Métricas gravadas! A IA priorizará os ganchos vencedores.');
    await refreshAll();
  } catch (e) {
    showToast(`Erro ao gravar feedback: ${e.message}`, true);
  }
}

function renderFeedback() {
  const el = document.getElementById('feedback-leaderboard');
  if (!STATE.feedback.length) {
    el.innerHTML = '<div class="text-[#B6A9D4]">Sem registros ainda. Informe as views após publicar.</div>';
    return;
  }
  el.innerHTML = STATE.feedback.map((f, idx) => `
    <div class="p-2.5 rounded-lg bg-[#0B0713]/80 border border-frimegold/25 flex items-center justify-between">
      <span><strong class="text-frimegold">#${idx + 1}</strong> ${f.skill_id}</span>
      <span class="text-frimelime font-bold">${Math.round(f.avg_views)} views • ${Number(f.avg_retention).toFixed(1)}% ret</span>
    </div>
  `).join('');
}

/* -------------------- Boot -------------------- */
initRemoteAccessControls();
setFactoryDuration(30);
updateLibraryMixCount();
updateMusicVolLabel();
updateAdvancedSummaryPill();
updateRecipeSummary();
refreshAll();
pollTelemetry();
setInterval(pollTelemetry, 4000);
setInterval(async () => {
  try {
    const j = await api('/api/jobs');
    STATE.jobs = j.jobs;
    renderJobs();
  } catch (e) {}
}, 3000);
