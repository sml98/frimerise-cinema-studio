/* FrimeRise Dashboard Client Logic — 3 Master Engines + Twin Channels + DNA X-Ray + Google Flow Pro */
let STATE = {
  settings: {},
  presets: [],
  clients: [],
  skills: [],
  luts: [],
  edge_voices: [],
  gemini_voices: [],
  flow_pro: { credits_remaining: 10000, credits_total: 10000 },
  doc_queue: { channels: {}, episodes: [] },
  jobs: [],
  schedules: [],
  feedback: [],
  activeMode: 'single',
  activeStyle: 'cinematic_broll',
  selectedVipJobId: null,
  lastAnalyzedDna: null,
};

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
      const match = Array.from(sk.options).find((o) => o.value.includes('10_netflix') || o.value.includes('02_curiosity'));
      if (match) sk.value = match.value;
      syncDocChannelSelection();
    }
  }
  updateManufactureCtaText();
}

document.querySelectorAll('.style-btn').forEach((btn) => {
  btn.addEventListener('click', () => selectEngineStyle(btn.dataset.style));
});

function syncDocChannelSelection() {
  const lang = document.getElementById('doc-lang')?.value || 'pt_br';
  const targetName = lang === 'en_us' ? 'Vault Files' : 'Dossiê Capital';
  const found = (STATE.clients || []).find((c) => c.name === targetName);
  const cliSel = document.getElementById('fac-client');
  if (found && cliSel) {
    cliSel.value = String(found.id);
  }
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
    renderPresetsGrid();
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
    const payload = {
      episode_id: Number(episodeId),
      target,
      aspect_ratio: document.getElementById('doc-aspect')?.value || '16:9',
      target_minutes: Number(document.getElementById('doc-minutes')?.value || 0.5),
      auto_shorts_cascade: true,
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

  // LUTs
  const lutSel = document.getElementById('cli-lut');
  lutSel.innerHTML = STATE.luts.map((l) => `<option value="${l}">${l.replace('.cube', '').replaceAll('_', ' ')}</option>`).join('');

  // Voice list synced to selected voice engine
  syncVoiceListForEngine();

  // Load first client into form if empty
  if (!document.getElementById('cli-id').value && STATE.clients.length > 0) {
    loadClientIntoForm(STATE.clients[0]);
  }
}

function syncVoiceListForEngine(preferredVoiceId = null) {
  const eng = document.getElementById('cli-voice-engine').value || 'edge';
  const vSel = document.getElementById('cli-voice-id');
  const prev = preferredVoiceId || vSel.value;
  const edgeWithUs = [
    ...(STATE.edge_voices || []),
    { id: 'en-US-AndrewMultilingualNeural', name: 'Andrew Multilingual (EN-US • Vault Files Grave)' },
    { id: 'es-MX-DaliaNeural', name: 'Dalia Neural (ES-MX • Espanhol Nativo)' },
  ];
  const list = eng === 'gemini_tts' ? (STATE.gemini_voices || []) : edgeWithUs;
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

    const isDoc = STATE.activeStyle === 'netflix_doc';
    const aspectRatio = isDoc
      ? (document.getElementById('doc-aspect')?.value || '16:9')
      : (document.getElementById('fac-aspect')?.value || '9:16');

    const payload = {
      client_id: Number(document.getElementById('fac-client').value || 1),
      mode: STATE.activeMode,
      engine_style: STATE.activeStyle,
      aspect_ratio: aspectRatio,
      cartoon_tone: document.getElementById('fac-tone')?.value || 'Comédia Nordestina/BR',
      cartoon_fps: Number(document.getElementById('fac-fps')?.value || 60),
      cartoon_voice_engine: document.getElementById('fac-cartoon-voice')?.value || 'gemini_tts',
      clone_languages: Boolean(document.getElementById('opt-clone-langs')?.checked),
      flow_mode: document.getElementById('fac-flow-mode')?.value || 'economico_pro',
      max_credits_cap: Number(document.getElementById('fac-flow-cap')?.value || 45),
      use_flow_music: Boolean(document.getElementById('opt-flow-music')?.checked),
      doc_lang: document.getElementById('doc-lang')?.value || 'pt_br',
      target_minutes: Number(document.getElementById('doc-minutes')?.value || 0.5),
      thumb_3words: (document.getElementById('doc-thumb-hook')?.value || '').trim() || null,
      auto_shorts_cascade: Boolean(document.getElementById('opt-ab')?.checked),
      topic: document.getElementById('fac-topic').value.trim(),
      batch_topics: batchLines,
      source_url: document.getElementById('fac-url').value.trim(),
      reference_mp4_path: document.getElementById('fac-ref-mp4-path').value.trim(),
      skill_id: document.getElementById('fac-skill').value,
      motion_cards: document.getElementById('opt-motion').checked,
      seamless_loop: document.getElementById('opt-loop').checked,
      dual_hook_ab: document.getElementById('opt-ab').checked,
    };
    const res = await api('/api/factory/manufacture', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast(`🚀 ${res.count} vídeo(s) enviado(s) para a fábrica FrimeRise (${STATE.activeStyle})!`);
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
      return `
        <div class="p-3.5 rounded-xl bg-[#0B0713]/85 border border-[rgba(179,136,255,0.2)] space-y-2">
          <div class="flex items-start justify-between gap-2">
            <strong class="text-xs text-white line-clamp-2">${j.topic}</strong>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border ${badgeColor} shrink-0">${j.status}</span>
          </div>
          <div class="flex items-center justify-between text-[11px] text-[#B6A9D4]">
            <span>${j.client_name || 'FrimeRise'} • ${engTag} • ${j.duration_s || 0}s</span>
            <span class="text-frimegold font-bold">${j.views_count || 0} views</span>
          </div>
          ${j.status === 'completed' ? `<button type="button" onclick="openInVip('${j.id}')" class="btn-gold w-full py-1.5 text-[11px]">👑 Abrir na Central VIP</button>` : `<div class="lime-progress-track"><div class="lime-progress-fill" style="width:${j.progress}%"></div></div>`}
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

function renderVipJob(jobId) {
  const job = STATE.jobs.find((j) => j.id === jobId);
  if (!job) return;

  const pA = document.getElementById('player-hook-a');
  const pB = document.getElementById('player-hook-b');
  const srcA = job.hook_a_path ? `/${job.hook_a_path}` : (job.master_path ? `/${job.master_path}` : '');
  const srcB = job.hook_b_path ? `/${job.hook_b_path}` : srcA;

  if (pA.getAttribute('data-src') !== srcA) {
    pA.setAttribute('data-src', srcA);
    pA.src = srcA;
  }
  if (pB.getAttribute('data-src') !== srcB) {
    pB.setAttribute('data-src', srcB);
    pB.src = srcB;
  }

  document.getElementById('dl-master').href = `/api/download/${job.id}/master`;
  document.getElementById('dl-capcut').href = `/api/download/${job.id}/capcut`;
  document.getElementById('dl-preview').href = `/api/download/${job.id}/preview`;
  document.getElementById('dl-otio').href = `/api/download/${job.id}/otio`;
  document.getElementById('dl-cover').href = `/api/download/${job.id}/cover`;
  document.getElementById('dl-hookb').href = job.hook_b_path ? `/api/download/${job.id}/hook_b` : `/api/download/${job.id}/master`;
  document.getElementById('dl-tiktok').href = `/api/download/${job.id}/tiktok`;
  document.getElementById('dl-reels').href = `/api/download/${job.id}/reels`;
  document.getElementById('dl-shorts').href = `/api/download/${job.id}/shorts`;

  if (job.cover_path) {
    document.getElementById('vip-cover-img').src = `/${job.cover_path}`;
  }
  const qr = job.quality_report || {};
  document.getElementById('vip-job-meta').innerHTML = `
    <strong class="text-white block text-sm mb-1">${job.topic}</strong>
    Motor: <span class="text-frimepink font-bold">${qr.engine_style || 'cinematic_broll'}</span> • Duração: <span class="text-frimelime font-bold">${job.duration_s}s</span> • Formato: <span class="text-frimelilac font-bold">${qr.aspect_ratio || '9:16'}</span> • Custo: <span class="text-frimegold font-bold">$${Number(job.cost_usd || 0).toFixed(5)}</span>
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
  document.getElementById('set-llm').value = s.default_llm || 'gemini-3.5-flash-lite';
  document.getElementById('set-ollama').value = s.ollama_url || 'http://localhost:11434';
  document.getElementById('set-thermal').value = s.thermal_limit_c || '85';
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
