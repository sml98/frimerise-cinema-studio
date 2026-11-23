import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { StudioStore, convertBrtToShanghai } from './store.ts';
import { buildB2BCommercialBundle, buildEdlTimeline, synthesizeViralScript } from './pipeline.ts';
import { createSessionToken, hashPassword, sanitizeNextUrl, verifyPassword, verifySessionToken } from './auth.ts';
import { renderStudioMp4, renderStyledImage, renderVoicePreviewWav } from './media.ts';

const REPO_ROOT = path.resolve(process.cwd());

test('StudioStore seeds 7 presets, 3 clients including Twin Channels, 11 skills, and 10 doc episodes', () => {
  const store = new StudioStore(REPO_ROOT);
  const presets = store.listPresets();
  const clients = store.listClients();
  const skills = store.listSkills();
  const queue = store.getTwinChannelsQueue();

  assert.equal(presets.length, 7);
  assert.ok(clients.some((c) => c.name === 'Dossiê Capital'));
  assert.ok(clients.some((c) => c.name === 'Vault Files'));
  assert.equal(skills.length, 11);
  assert.equal(queue.episodes.length, 10);
  assert.equal(queue.channels.pt_br.name, 'Dossiê Capital');
  assert.equal(queue.channels.en_us.name, 'Vault Files');
});

test('StudioStore client upsert, schedule conversion, and feedback leaderboard work deterministically', () => {
  const store = new StudioStore(REPO_ROOT);
  const created = store.upsertClient({
    name: 'Clínica Estética Nova',
    niche: 'Estética Local',
    preset_id: 'local_business_ugc',
  });
  assert.ok(created.id >= 4);

  const job = store.createJob({
    client_id: created.id,
    topic: 'Campanha local de alta conversão',
    skill_id: '07_local_business_ad',
    mode: 'single',
    options: { engine_style: 'cinematic_broll' },
  });
  assert.equal(job.status, 'queued');

  const sched = store.createSchedule({
    job_id: job.id,
    client_id: created.id,
    platform: 'facebook',
    scheduled_brt: '2026-11-23T10:00',
    caption: 'Teste',
  });
  assert.equal(sched.scheduled_target_tz, '2026-11-23T21:00');
  assert.equal(convertBrtToShanghai('2026-11-23T18:30'), '2026-11-24T05:30');

  const fb = store.recordFeedback({
    job_id: job.id,
    platform: 'tiktok',
    views: 42000,
    likes: 3100,
    retention_pct: 68.5,
    hook_variant: 'A',
  });
  assert.equal(fb.leaderboard.length, 1);
  assert.equal(fb.leaderboard[0].skill_id, '07_local_business_ad');
  assert.equal(fb.leaderboard[0].avg_views, 42000);
});

test('Pure script synthesizer, B2B bundle, and EDL builder produce valid structures', () => {
  const docScript = synthesizeViralScript({
    topic: 'A queda do Barings Bank',
    language: 'pt_br',
    engineStyle: 'netflix_doc',
    targetDurationSec: 180,
  });
  assert.equal(docScript.retention_audit.abrupt_ending, true);
  assert.ok(docScript.hook_a.includes('Barings Bank'));

  const b2b = buildB2BCommercialBundle({
    companyName: 'Odonto Prime',
    city: 'Fortaleza',
    productService: 'Implantes Dentários',
  });
  assert.ok(b2b.whatsapp_pitch.includes('Odonto Prime'));
  assert.ok(b2b.whatsapp_pitch.includes('Fortaleza'));

  const edl = buildEdlTimeline('job_test', 'Barings Bank', 180, 'netflix_doc');
  assert.equal(edl.scenes.length, 5);
  assert.equal(edl.scenes[4].end_s, 180);
});

test('Auth helpers hash/verify passwords, sign sessions, and sanitize redirect URLs', () => {
  const hash = hashPassword('supersecret123');
  assert.equal(verifyPassword('supersecret123', hash), true);
  assert.equal(verifyPassword('wrongpass', hash), false);

  const token = createSessionToken('frimerise', 'test-secret', 3600);
  assert.equal(verifySessionToken(token, 'test-secret'), 'frimerise');
  assert.equal(verifySessionToken(token, 'other-secret'), null);

  assert.equal(sanitizeNextUrl('/vip'), '/vip');
  assert.equal(sanitizeNextUrl('https://evil.com'), '/');
  assert.equal(sanitizeNextUrl('//evil.com'), '/');
});

test('FFmpeg media helpers render MP4, styled thumbnail JPG, and WAV voice preview rapidly', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'frimerise-media-'));
  try {
    const t0 = Date.now();
    const mp4Path = path.join(tmpDir, 'master.mp4');
    const jpgPath = path.join(tmpDir, 'thumb.jpg');
    const wavPath = path.join(tmpDir, 'voice.wav');
    const musicPath = path.join(REPO_ROOT, 'assets', 'music', 'epic_doc.mp3');
    const logoPath = path.join(REPO_ROOT, 'assets', 'brand', 'frimerise_logo.png');

    const mp4Ok = await renderStudioMp4({
      outputPath: mp4Path,
      aspectRatio: '16:9',
      durationSec: 4,
      bgColorHex: '#140E24',
      accentColorHex: '#B8FF01',
      logoPath,
      musicPath,
    });
    const jpgOk = await renderStyledImage({
      outputPath: jpgPath,
      width: 1280,
      height: 720,
      primaryHex: '#0B0713',
      accentHex: '#B8FF01',
      logoPath,
    });
    const wavRes = await renderVoicePreviewWav({
      outputPath: wavPath,
      voiceId: 'pt-BR-AntonioNeural',
      rate: '+0%',
      pitch: '+0Hz',
    });

    const elapsedMs = Date.now() - t0;
    assert.equal(mp4Ok, true);
    assert.equal(jpgOk, true);
    assert.equal(wavRes.ok, true);
    assert.ok(fs.statSync(mp4Path).size > 2000, 'MP4 should contain real video bytes');
    assert.ok(fs.statSync(jpgPath).size > 1000, 'JPG should contain real image bytes');
    assert.ok(fs.statSync(wavPath).size > 4000, 'WAV should contain real audio bytes');
    assert.ok(elapsedMs < 10000, `Media rendering should be fast, took ${elapsedMs}ms`);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
