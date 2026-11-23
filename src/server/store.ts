import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {
  DEFAULT_PRESETS,
  TEN_DOCUMENTARY_EPISODES,
  TWIN_CHANNELS_SPEC,
  type DocEpisode,
  type PresetRecord,
  type TwinChannelSpec,
} from './catalogs.ts';
import { hashPassword } from './auth.ts';

export interface ClientRecord {
  id: number;
  name: string;
  niche: string;
  preset_id: string;
  lut_file: string;
  voice_engine: string;
  voice_id: string;
  voice_blend: string;
  logo_path: string;
  proxy_url: string;
  watermark_text: string;
  tiktok_connected: number;
  youtube_connected: number;
  facebook_connected: number;
  created_at: string;
}

export interface JobRecord {
  id: string;
  client_id: number;
  client_name?: string;
  mode: string;
  topic: string;
  skill_id: string;
  status: 'queued' | 'running' | 'completed' | 'error';
  progress: number;
  stage: string;
  log: string;
  script_json: string;
  options_json: string;
  master_path: string;
  hook_a_path: string;
  hook_b_path: string;
  tiktok_path: string;
  reels_path: string;
  shorts_path: string;
  preview_path: string;
  capcut_zip_path: string;
  otio_path: string;
  cover_path: string;
  duration_s: number;
  tokens_used: number;
  cost_usd: number;
  views_count: number;
  created_at: string;
  completed_at: string;
  quality_report?: Record<string, unknown>;
  qc_report?: Record<string, unknown>;
  gdrive_backup?: Record<string, unknown>;
  drive_url?: string;
  artifacts_available?: Record<string, boolean>;
}

export interface ScheduleRecord {
  id: number;
  job_id: string;
  client_id: number;
  topic?: string;
  platform: string;
  scheduled_brt: string;
  scheduled_target_tz: string;
  caption: string;
  status: string;
  result_log: string;
  created_at: string;
}

export interface FeedbackRecord {
  id: number;
  job_id: string;
  skill_id: string;
  hook_variant: string;
  platform: string;
  views: number;
  likes: number;
  retention_pct: number;
  recorded_at: string;
}

export interface SkillInfo {
  id: string;
  name: string;
  file: string;
}

export interface TwinChannelsQueueData {
  updated_at: string;
  channels: {
    pt_br: TwinChannelSpec & { client_id: number };
    en_us: TwinChannelSpec & { client_id: number };
  };
  episodes: DocEpisode[];
}

export function isoNow(): string {
  return new Date().toISOString().slice(0, 19);
}

export function convertBrtToShanghai(brtIso: string): string {
  // BRT is UTC-3, Asia/Shanghai is UTC+8 => +11 hours offset
  const normalized = brtIso.includes('T') ? brtIso : brtIso.replace(' ', 'T');
  const parsed = new Date(`${normalized.slice(0, 16)}:00-03:00`);
  if (Number.isNaN(parsed.getTime())) return brtIso;
  const shanghaiMs = parsed.getTime() + 8 * 3600 * 1000;
  const d = new Date(shanghaiMs);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

export class StudioStore {
  readonly baseDir: string;
  readonly assetsDir: string;
  readonly skillsDir: string;
  readonly outputsDir: string;
  readonly dataDir: string;

  private settings = new Map<string, string>();
  private presets = new Map<string, PresetRecord>();
  private clients = new Map<number, ClientRecord>();
  private jobs = new Map<string, JobRecord>();
  private schedules: ScheduleRecord[] = [];
  private feedback: FeedbackRecord[] = [];
  private flowCreditsRemaining = 10000;
  private nextClientId = 1;
  private nextScheduleId = 1;
  private nextFeedbackId = 1;

  constructor(baseDir: string) {
    this.baseDir = baseDir;
    this.assetsDir = path.join(baseDir, 'assets');
    this.skillsDir = path.join(baseDir, 'skills');
    this.outputsDir = path.join(baseDir, 'outputs');
    this.dataDir = path.join(baseDir, 'data');

    fs.mkdirSync(this.outputsDir, { recursive: true });
    fs.mkdirSync(path.join(this.dataDir, 'logos'), { recursive: true });
    fs.mkdirSync(path.join(this.dataDir, 'ref_cache'), { recursive: true });
    fs.mkdirSync(path.join(this.dataDir, 'references'), { recursive: true });

    this.seedDefaults();
  }

  private seedDefaults(): void {
    const now = isoNow();
    this.settings.set('default_llm', 'gemini-2.5-flash-lite');
    this.settings.set('ollama_url', process.env.OLLAMA_URL || 'http://localhost:11434');
    this.settings.set('thermal_limit_c', '85');
    this.settings.set('gdrive_root_folder', 'FrimeRise');
    this.settings.set('gdrive_auto_upload', '1');
    this.settings.set('gdrive_prune_local', '1');
    this.settings.set('gdrive_local_dir', '');
    this.settings.set('auth_username', 'frimerise');
    this.settings.set('auth_require_local', '0');
    this.settings.set('auth_session_secret', crypto.randomBytes(32).toString('hex'));
    this.settings.set('auth_password_hash', hashPassword('frimerise2026'));

    if (process.env.GEMINI_API_KEY) this.settings.set('gemini_api_key', process.env.GEMINI_API_KEY);
    if (process.env.DEEPSEEK_API_KEY) this.settings.set('deepseek_api_key', process.env.DEEPSEEK_API_KEY);
    if (process.env.PIXABAY_API_KEY) this.settings.set('pixabay_api_key', process.env.PIXABAY_API_KEY);
    if (process.env.PEXELS_API_KEY) this.settings.set('pexels_api_key', process.env.PEXELS_API_KEY);

    for (const preset of DEFAULT_PRESETS) {
      this.presets.set(preset.id, { ...preset });
    }

    // Seed default showcase client (#1)
    this.upsertClient({
      name: 'FrimeRise Showcase',
      niche: 'Negócios, IA & Vídeos Virais',
      preset_id: 'frimerise_signature',
      lut_file: '01_frimerise_signature.cube',
      voice_engine: 'edge',
      voice_id: 'pt-BR-AntonioNeural',
      voice_blend: { pf_dora: 0.35, pm_alex: 0.65, pm_santa: 0.0 },
      logo_path: 'assets/brand/frimerise_logo.png',
      proxy_url: '',
      watermark_text: 'PRÉVIA • FRIMERISE',
    });

    // Seed Twin Channels (#2 Dossiê Capital BR, #3 Vault Files US)
    for (const ch of TWIN_CHANNELS_SPEC) {
      this.upsertClient({
        name: ch.name,
        niche: ch.niche,
        preset_id: ch.preset_id,
        lut_file: ch.lut_file,
        voice_engine: ch.voice_engine,
        voice_id: ch.voice_id,
        voice_blend: ch.voice_blend,
        logo_path: ch.logo_path,
        proxy_url: '',
        watermark_text: ch.watermark_text,
      });
    }
  }

  getSettings(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [k, v] of this.settings.entries()) {
      out[k] = v;
    }
    return out;
  }

  saveSettings(updates: Record<string, unknown>): Record<string, string> {
    for (const [k, v] of Object.entries(updates)) {
      if (v === undefined || v === null) continue;
      this.settings.set(k, String(v));
    }
    return this.getSettings();
  }

  getAuthSecret(): string {
    let secret = this.settings.get('auth_session_secret');
    if (!secret) {
      secret = crypto.randomBytes(32).toString('hex');
      this.settings.set('auth_session_secret', secret);
    }
    return secret;
  }

  updateCredentials(params: { username?: string | null; new_password?: string | null; require_local?: boolean | null }) {
    let passwordRotated = false;
    const currentUsername = this.settings.get('auth_username') || 'frimerise';
    const nextUsername = (params.username ?? currentUsername).trim();
    if (!nextUsername || nextUsername.length < 3) {
      throw new Error('O usuário deve ter ao menos 3 caracteres.');
    }
    this.settings.set('auth_username', nextUsername);

    if (params.new_password && params.new_password.trim().length > 0) {
      if (params.new_password.length < 8) {
        throw new Error('A nova senha deve ter ao menos 8 caracteres.');
      }
      this.settings.set('auth_password_hash', hashPassword(params.new_password));
      this.settings.set('auth_session_secret', crypto.randomBytes(32).toString('hex'));
      passwordRotated = true;
    }

    if (typeof params.require_local === 'boolean') {
      this.settings.set('auth_require_local', params.require_local ? '1' : '0');
    }

    return {
      auth_username: this.settings.get('auth_username') || 'frimerise',
      auth_require_local: this.settings.get('auth_require_local') === '1',
      password_rotated: passwordRotated,
    };
  }

  listPresets(): PresetRecord[] {
    return Array.from(this.presets.values());
  }

  getPreset(id: string): PresetRecord {
    return this.presets.get(id) || this.presets.get('frimerise_signature') || DEFAULT_PRESETS[0];
  }

  savePreset(preset: PresetRecord): PresetRecord {
    this.presets.set(preset.id, { ...preset });
    return { ...preset };
  }

  listClients(): ClientRecord[] {
    return Array.from(this.clients.values()).sort((a, b) => a.id - b.id);
  }

  getClient(id: number): ClientRecord | undefined {
    return this.clients.get(Number(id));
  }

  upsertClient(input: {
    id?: number | null;
    name: string;
    niche?: string;
    preset_id?: string;
    lut_file?: string;
    voice_engine?: string;
    voice_id?: string;
    voice_blend?: Record<string, number> | string;
    logo_path?: string;
    proxy_url?: string;
    watermark_text?: string;
  }): ClientRecord {
    const existing = input.id ? this.clients.get(Number(input.id)) : undefined;
    const id = existing ? existing.id : this.nextClientId++;
    const blendStr =
      typeof input.voice_blend === 'string'
        ? input.voice_blend
        : JSON.stringify(input.voice_blend || { pf_dora: 0.35, pm_alex: 0.65, pm_santa: 0.0 });

    const rec: ClientRecord = {
      id,
      name: (input.name || 'Novo Cliente').trim(),
      niche: (input.niche || 'Negócios & IA').trim(),
      preset_id: input.preset_id || 'frimerise_signature',
      lut_file: input.lut_file || '01_frimerise_signature.cube',
      voice_engine: input.voice_engine || 'edge',
      voice_id: input.voice_id || 'pt-BR-AntonioNeural',
      voice_blend: blendStr,
      logo_path: input.logo_path || 'assets/brand/frimerise_logo.png',
      proxy_url: input.proxy_url || '',
      watermark_text: input.watermark_text || 'PRÉVIA • FRIMERISE',
      tiktok_connected: existing?.tiktok_connected ?? 0,
      youtube_connected: existing?.youtube_connected ?? 0,
      facebook_connected: existing?.facebook_connected ?? 0,
      created_at: existing?.created_at || isoNow(),
    };
    this.clients.set(id, rec);
    return { ...rec };
  }

  markClientPlatformConnected(clientId: number, platform: 'tiktok' | 'youtube' | 'facebook'): void {
    const client = this.clients.get(clientId);
    if (!client) return;
    if (platform === 'tiktok') client.tiktok_connected = 1;
    if (platform === 'youtube') client.youtube_connected = 1;
    if (platform === 'facebook') client.facebook_connected = 1;
  }

  listSkills(): SkillInfo[] {
    if (!fs.existsSync(this.skillsDir)) return [];
    return fs
      .readdirSync(this.skillsDir)
      .filter((f) => f.endsWith('.md'))
      .sort()
      .map((file) => {
        const full = path.join(this.skillsDir, file);
        const firstLine = fs.readFileSync(full, 'utf-8').split(/\r?\n/)[0]?.replace(/^#+\s*/, '').trim() || file;
        return {
          id: file.replace(/\.md$/, ''),
          name: firstLine,
          file,
        };
      });
  }

  listAssetFiles(subdir: 'luts' | 'sfx' | 'music', ext: string): string[] {
    const dir = path.join(this.assetsDir, subdir);
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((f) => f.endsWith(ext))
      .sort();
  }

  getTwinChannelsQueue(): TwinChannelsQueueData {
    const clientsByName = new Map(this.listClients().map((c) => [c.name, c.id]));
    const brId = clientsByName.get('Dossiê Capital') ?? 2;
    const usId = clientsByName.get('Vault Files') ?? 3;

    const jsonPath = path.join(this.dataDir, 'twin_channels_queue.json');
    if (fs.existsSync(jsonPath)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(jsonPath, 'utf-8')) as TwinChannelsQueueData;
        if (parsed?.channels?.pt_br && parsed?.channels?.en_us && Array.isArray(parsed.episodes)) {
          parsed.channels.pt_br.client_id = brId;
          parsed.channels.en_us.client_id = usId;
          return parsed;
        }
      } catch {
        // fallback to embedded spec
      }
    }

    return {
      updated_at: isoNow(),
      channels: {
        pt_br: { ...TWIN_CHANNELS_SPEC[0], client_id: brId },
        en_us: { ...TWIN_CHANNELS_SPEC[1], client_id: usId },
      },
      episodes: TEN_DOCUMENTARY_EPISODES,
    };
  }

  getDocEpisode(episodeId: number): DocEpisode | undefined {
    return this.getTwinChannelsQueue().episodes.find((e) => Number(e.id) === Number(episodeId));
  }

  createJob(params: {
    client_id: number;
    topic: string;
    skill_id: string;
    mode: string;
    options: Record<string, unknown>;
  }): JobRecord {
    const id = `job_${Date.now().toString(36)}_${crypto.randomBytes(3).toString('hex')}`;
    const client = this.getClient(params.client_id);
    const job: JobRecord = {
      id,
      client_id: params.client_id,
      client_name: client?.name || 'FrimeRise Studio',
      mode: params.mode || 'single',
      topic: params.topic,
      skill_id: params.skill_id || '01_negative_hook',
      status: 'queued',
      progress: 0,
      stage: 'Na fila de produção...',
      log: `[${isoNow()}] 🎬 Job ${id} criado na fila sequencial FrimeRise.`,
      script_json: '{}',
      options_json: JSON.stringify(params.options || {}),
      master_path: '',
      hook_a_path: '',
      hook_b_path: '',
      tiktok_path: '',
      reels_path: '',
      shorts_path: '',
      preview_path: '',
      capcut_zip_path: '',
      otio_path: '',
      cover_path: '',
      duration_s: 0,
      tokens_used: 0,
      cost_usd: 0,
      views_count: 0,
      created_at: isoNow(),
      completed_at: '',
    };
    this.jobs.set(id, job);
    return this.enrichJob(job);
  }

  getJob(jobId: string): JobRecord | undefined {
    const j = this.jobs.get(jobId);
    return j ? this.enrichJob(j) : undefined;
  }

  listJobs(limit = 50): JobRecord[] {
    return Array.from(this.jobs.values())
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
      .slice(0, limit)
      .map((j) => this.enrichJob(j));
  }

  updateJob(jobId: string, patch: Partial<JobRecord>): JobRecord | undefined {
    const existing = this.jobs.get(jobId);
    if (!existing) return undefined;
    Object.assign(existing, patch);
    return this.enrichJob(existing);
  }

  appendJobLog(jobId: string, line: string): void {
    const existing = this.jobs.get(jobId);
    if (!existing) return;
    existing.log = existing.log ? `${existing.log}\n[${isoNow()}] ${line}` : `[${isoNow()}] ${line}`;
  }

  enrichJob(raw: JobRecord): JobRecord {
    const job: JobRecord = { ...raw };
    const client = this.getClient(job.client_id);
    job.client_name = client?.name || job.client_name || 'FrimeRise Studio';

    const jobDir = path.join(this.outputsDir, job.id);
    const qrPath = path.join(jobDir, 'quality_report.json');
    const qcPath = path.join(jobDir, 'qc_report.json');

    let qr: Record<string, unknown> = {};
    if (fs.existsSync(qrPath)) {
      try {
        qr = JSON.parse(fs.readFileSync(qrPath, 'utf-8')) as Record<string, unknown>;
      } catch {
        qr = {};
      }
    }
    let qc: Record<string, unknown> = {};
    if (fs.existsSync(qcPath)) {
      try {
        qc = JSON.parse(fs.readFileSync(qcPath, 'utf-8')) as Record<string, unknown>;
      } catch {
        qc = {};
      }
    }

    job.quality_report = qr;
    job.qc_report = qc;
    const gd = (qr.gdrive_backup as Record<string, unknown> | undefined) || {};
    job.gdrive_backup = gd;
    job.drive_url = String(gd.drive_url || '');

    const existsRel = (rel: string) => Boolean(rel && fs.existsSync(path.join(this.baseDir, rel)));

    job.artifacts_available = {
      master: fs.existsSync(path.join(jobDir, 'master.mp4')),
      preview: fs.existsSync(path.join(jobDir, 'preview_540p.mp4')),
      edl: fs.existsSync(path.join(jobDir, 'edl_timeline.json')),
      script: fs.existsSync(path.join(jobDir, 'script.json')) || (Boolean(job.script_json) && job.script_json !== '{}'),
      qc: fs.existsSync(qcPath),
      quality_report: fs.existsSync(qrPath),
      capcut: fs.existsSync(path.join(jobDir, 'capcut_project.zip')),
      otio: fs.existsSync(path.join(jobDir, 'timeline.otio')),
      cover: fs.existsSync(path.join(jobDir, 'cover_9x16.png')),
      tiktok: existsRel(job.tiktok_path),
      reels: existsRel(job.reels_path),
      shorts: existsRel(job.shorts_path),
      hook_b: existsRel(job.hook_b_path),
    };

    return job;
  }

  createSchedule(params: {
    job_id: string;
    client_id: number;
    platform: string;
    scheduled_brt: string;
    caption: string;
  }): ScheduleRecord {
    const job = this.jobs.get(params.job_id);
    const targetTz =
      params.platform === 'facebook' || params.platform === 'reels'
        ? convertBrtToShanghai(params.scheduled_brt)
        : params.scheduled_brt;
    const sched: ScheduleRecord = {
      id: this.nextScheduleId++,
      job_id: params.job_id,
      client_id: params.client_id,
      topic: job?.topic || params.job_id,
      platform: params.platform,
      scheduled_brt: params.scheduled_brt,
      scheduled_target_tz: targetTz,
      caption: params.caption || job?.topic || 'FrimeRise Studio',
      status: 'scheduled',
      result_log: '',
      created_at: isoNow(),
    };
    this.schedules.unshift(sched);
    return { ...sched };
  }

  listSchedules(): ScheduleRecord[] {
    return this.schedules.map((s) => ({ ...s }));
  }

  recordFeedback(params: {
    job_id: string;
    platform: string;
    views: number;
    likes: number;
    retention_pct: number;
    hook_variant: string;
  }) {
    const job = this.jobs.get(params.job_id);
    const skillId = job?.skill_id || '01_negative_hook';
    if (job) {
      job.views_count = Math.max(job.views_count, Number(params.views || 0));
    }
    this.feedback.push({
      id: this.nextFeedbackId++,
      job_id: params.job_id,
      skill_id: skillId,
      hook_variant: params.hook_variant || 'A',
      platform: params.platform || 'tiktok',
      views: Number(params.views || 0),
      likes: Number(params.likes || 0),
      retention_pct: Number(params.retention_pct || 0),
      recorded_at: isoNow(),
    });
    return {
      status: 'recorded',
      job_id: params.job_id,
      skill_id: skillId,
      leaderboard: this.getFeedbackLeaderboard(),
    };
  }

  getFeedbackLeaderboard(): Array<{ skill_id: string; avg_views: number; avg_retention: number; samples: number }> {
    const grouped = new Map<string, { views: number; retention: number; count: number }>();
    for (const f of this.feedback) {
      const cur = grouped.get(f.skill_id) || { views: 0, retention: 0, count: 0 };
      cur.views += f.views;
      cur.retention += f.retention_pct;
      cur.count += 1;
      grouped.set(f.skill_id, cur);
    }
    return Array.from(grouped.entries())
      .map(([skill_id, agg]) => ({
        skill_id,
        avg_views: agg.views / agg.count,
        avg_retention: agg.retention / agg.count,
        samples: agg.count,
      }))
      .sort((a, b) => b.avg_views - a.avg_views);
  }

  getTotalCostStats(): { total_usd: number; total_tokens: number; jobs_done: number } {
    let total_usd = 0;
    let total_tokens = 0;
    let jobs_done = 0;
    for (const j of this.jobs.values()) {
      total_usd += j.cost_usd || 0;
      total_tokens += j.tokens_used || 0;
      if (j.status === 'completed') jobs_done += 1;
    }
    return { total_usd: Number(total_usd.toFixed(5)), total_tokens, jobs_done };
  }

  getFlowStatus() {
    return {
      credits_remaining: this.flowCreditsRemaining,
      credits_total: 10000,
      authenticated: false,
      vault_ready: true,
      mode_default: 'economico_pro',
    };
  }

  consumeFlowCredits(amount: number): void {
    this.flowCreditsRemaining = Math.max(0, this.flowCreditsRemaining - Math.max(0, Math.round(amount)));
  }
}
