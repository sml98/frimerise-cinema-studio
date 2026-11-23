import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

function aspectDimensions(aspectRatio: string, preview = false): { w: number; h: number } {
  const scale = preview ? 0.5 : 1;
  switch (aspectRatio) {
    case '16:9':
      return { w: Math.round(1280 * scale), h: Math.round(720 * scale) };
    case '4:5':
      return { w: Math.round(720 * scale), h: Math.round(900 * scale) };
    case '1:1':
      return { w: Math.round(720 * scale), h: Math.round(720 * scale) };
    default:
      return { w: Math.round(720 * scale), h: Math.round(1280 * scale) };
  }
}

async function runFfmpeg(args: string[]): Promise<boolean> {
  try {
    await execFileAsync('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', ...args], {
      timeout: 25000,
    });
    return true;
  } catch {
    return false;
  }
}

export async function renderStudioMp4(params: {
  outputPath: string;
  aspectRatio: string;
  durationSec: number;
  bgColorHex: string;
  accentColorHex?: string;
  logoPath?: string;
  musicPath?: string;
  preview?: boolean;
}): Promise<boolean> {
  fs.mkdirSync(path.dirname(params.outputPath), { recursive: true });
  const { w, h } = aspectDimensions(params.aspectRatio, Boolean(params.preview));
  const dur = Math.max(2, Math.min(8, Math.round(params.durationSec || 4)));
  const color = params.bgColorHex.replace('#', '0x');
  const accent = (params.accentColorHex || '#B8FF01').replace('#', '0x');

  const hasMusic = Boolean(params.musicPath && fs.existsSync(params.musicPath));
  const hasLogo = Boolean(params.logoPath && fs.existsSync(params.logoPath));
  const logoSize = Math.round(Math.min(w, h) * 0.24);

  const baseBoxes =
    `drawbox=x=0:y=0:w=iw:h=12:color=${accent}@0.9:t=fill,` +
    `drawbox=x=0:y=ih-12:w=iw:h=12:color=0xFF2E93@0.9:t=fill,` +
    `drawbox=x=28:y=28:w=iw-56:h=ih-56:color=0xB388FF@0.5:t=3`;

  const args: string[] = [
    '-f',
    'lavfi',
    '-i',
    `color=c=${color}:s=${w}x${h}:d=${dur}:r=24`,
  ];

  if (hasLogo) {
    args.push('-i', params.logoPath!);
  }

  if (hasMusic) {
    args.push('-stream_loop', '-1', '-i', params.musicPath!);
  } else {
    args.push('-f', 'lavfi', '-i', `sine=frequency=220:duration=${dur}`);
  }

  const audioIdx = hasLogo ? 2 : 1;

  if (hasLogo) {
    args.push(
      '-filter_complex',
      `[0:v]${baseBoxes}[bg];[1:v]scale=${logoSize}:${logoSize}[lg];[bg][lg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vout]`,
      '-map',
      '[vout]',
      '-map',
      `${audioIdx}:a:0`
    );
  } else {
    args.push('-vf', `${baseBoxes},format=yuv420p`, '-map', '0:v:0', '-map', `${audioIdx}:a:0`);
  }

  if (!hasMusic) {
    args.push('-af', 'volume=0.06');
  }

  args.push(
    '-t',
    String(dur),
    '-c:v',
    'libx264',
    '-preset',
    'ultrafast',
    '-crf',
    '28',
    '-threads',
    '2',
    '-c:a',
    'aac',
    '-b:a',
    '96k',
    '-shortest',
    '-movflags',
    '+faststart',
    params.outputPath
  );

  const ok = await runFfmpeg(args);
  if (ok) return true;

  // Ultra-fast fallback without geq filter
  return runFfmpeg([
    '-f',
    'lavfi',
    '-i',
    `color=c=${color}:s=${w}x${h}:d=${dur}:r=24`,
    '-f',
    'lavfi',
    '-i',
    `anullsrc=r=44100:cl=stereo`,
    '-t',
    String(dur),
    '-pix_fmt',
    'yuv420p',
    '-c:v',
    'libx264',
    '-preset',
    'ultrafast',
    '-c:a',
    'aac',
    '-movflags',
    '+faststart',
    params.outputPath,
  ]);
}

export async function renderStyledImage(params: {
  outputPath: string;
  width: number;
  height: number;
  primaryHex: string;
  accentHex: string;
  logoPath?: string;
}): Promise<boolean> {
  fs.mkdirSync(path.dirname(params.outputPath), { recursive: true });
  const bg = params.primaryHex.replace('#', '0x');
  const accent = params.accentHex.replace('#', '0x');

  const hasLogo = Boolean(params.logoPath && fs.existsSync(params.logoPath));
  if (hasLogo) {
    const logoSize = Math.round(Math.min(params.width, params.height) * 0.28);
    const ok = await runFfmpeg([
      '-f',
      'lavfi',
      '-i',
      `color=c=${bg}:s=${params.width}x${params.height}:d=1`,
      '-i',
      params.logoPath!,
      '-filter_complex',
      `[0:v]drawbox=x=0:y=0:w=iw:h=14:color=${accent}:t=fill,drawbox=x=0:y=ih-14:w=iw:h=14:color=${accent}:t=fill,drawbox=x=36:y=36:w=iw-72:h=ih-72:color=${accent}@0.55:t=4[bg];[1:v]scale=${logoSize}:${logoSize}[lg];[bg][lg]overlay=(W-w)/2:(H-h)/2`,
      '-frames:v',
      '1',
      params.outputPath,
    ]);
    if (ok) return true;
  }

  return runFfmpeg([
    '-f',
    'lavfi',
    '-i',
    `color=c=${bg}:s=${params.width}x${params.height}:d=1`,
    '-vf',
    `drawbox=x=0:y=0:w=iw:h=16:color=${accent}:t=fill`,
    '-frames:v',
    '1',
    params.outputPath,
  ]);
}

export async function renderVoicePreviewWav(params: {
  outputPath: string;
  voiceId: string;
  rate: string;
  pitch: string;
  durationSec?: number;
}): Promise<{ ok: boolean; duration_s: number }> {
  fs.mkdirSync(path.dirname(params.outputPath), { recursive: true });
  const baseDur = params.durationSec ?? 3.2;
  const hash = Array.from(params.voiceId).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  const baseFreq = 190 + (hash % 180);
  const pitchOffset = params.pitch.includes('-8')
    ? -35
    : params.pitch.includes('-4')
      ? -18
      : params.pitch.includes('+8')
        ? 45
        : params.pitch.includes('+4')
          ? 22
          : 0;
  const freq = Math.max(120, baseFreq + pitchOffset);

  const ok = await runFfmpeg([
    '-f',
    'lavfi',
    '-i',
    `aevalsrc=0.18*sin(2*PI*${freq}*t)*(0.6+0.4*sin(2*PI*3.2*t))+0.08*sin(2*PI*${Math.round(freq * 1.5)}*t):s=44100:d=${baseDur}`,
    '-af',
    'afade=t=in:st=0:d=0.15,afade=t=out:st=2.8:d=0.4',
    '-c:a',
    'pcm_s16le',
    params.outputPath,
  ]);
  return { ok, duration_s: Number(baseDur.toFixed(1)) };
}
