import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { Request } from 'express';

export const HTTP_COOKIE_NAME = 'frimerise_session';
export const HTTPS_COOKIE_NAME = '__Host-frimerise_session';
export const CSRF_COOKIE_NAME = 'frimerise_csrf';
export const SESSION_TTL_SECONDS = 14 * 24 * 3600;

const SECRET_SETTINGS_KEYS = new Set([
  'auth_password_hash',
  'auth_session_secret',
]);

export function hashPassword(password: string, salt?: string): string {
  const actualSalt = salt || crypto.randomBytes(16).toString('hex');
  const derived = crypto.pbkdf2Sync(password, actualSalt, 120000, 32, 'sha256').toString('hex');
  return `pbkdf2_sha256$120000$${actualSalt}$${derived}`;
}

export function verifyPassword(password: string, storedHash: string): boolean {
  if (!storedHash || !password) return false;
  const parts = storedHash.split('$');
  if (parts.length !== 4 || parts[0] !== 'pbkdf2_sha256') return false;
  const iterations = Number(parts[1]) || 120000;
  const salt = parts[2];
  const expected = parts[3];
  const derived = crypto.pbkdf2Sync(password, salt, iterations, 32, 'sha256').toString('hex');
  const a = Buffer.from(derived, 'hex');
  const b = Buffer.from(expected, 'hex');
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

export function createSessionToken(username: string, secret: string, ttlSeconds = SESSION_TTL_SECONDS): string {
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const payload = Buffer.from(JSON.stringify({ u: username, exp })).toString('base64url');
  const sig = crypto.createHmac('sha256', secret).update(payload).digest('base64url');
  return `${payload}.${sig}`;
}

export function verifySessionToken(token: string | undefined, secret: string): string | null {
  if (!token || !secret || !token.includes('.')) return null;
  const [payload, sig] = token.split('.');
  if (!payload || !sig) return null;
  const expectedSig = crypto.createHmac('sha256', secret).update(payload).digest('base64url');
  const a = Buffer.from(sig);
  const b = Buffer.from(expectedSig);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    const parsed = JSON.parse(Buffer.from(payload, 'base64url').toString('utf-8')) as { u?: string; exp?: number };
    if (!parsed.u || !parsed.exp || parsed.exp < Math.floor(Date.now() / 1000)) return null;
    return parsed.u;
  } catch {
    return null;
  }
}

export function sanitizeNextUrl(raw?: string): string {
  const val = (raw || '/').trim();
  if (!val.startsWith('/') || val.startsWith('//') || val.includes('\\')) return '/';
  return val;
}

export function escapeHtml(str: string): string {
  return str
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function renderLoginHtml(
  templatePath: string,
  params: {
    cspNonce: string;
    csrfToken: string;
    nextUrl: string;
    usernameValue: string;
    errorMessage: string;
  }
): string {
  let html = fs.readFileSync(templatePath, 'utf-8');
  if (params.errorMessage) {
    html = html
      .replace(/\{%\s*if error_message\s*%\}/g, '')
      .replace(/\{%\s*endif\s*%\}/g, '')
      .replace(/\{\{\s*error_message\s*\}\}/g, escapeHtml(params.errorMessage));
  } else {
    html = html.replace(/\{%\s*if error_message\s*%\}[\s\S]*?\{%\s*endif\s*%\}/g, '');
  }
  html = html
    .replace(/\{\{\s*csrf_token\s*\}\}/g, escapeHtml(params.csrfToken))
    .replace(/\{\{\s*next_url\s*\}\}/g, escapeHtml(params.nextUrl))
    .replace(/\{\{\s*username_value\s*\}\}/g, escapeHtml(params.usernameValue))
    .replace(/\{\{\s*csp_nonce\s*\}\}/g, escapeHtml(params.cspNonce));
  return html;
}

export function isHttpsRequest(req: Request): boolean {
  const proto = String(req.headers['x-forwarded-proto'] || req.protocol || 'http').split(',')[0].trim();
  return proto === 'https';
}

export function extractAuthenticatedUser(req: Request, secret: string): string | null {
  const cookies = (req.cookies || {}) as Record<string, string | undefined>;
  const token = cookies[HTTPS_COOKIE_NAME] || cookies[HTTP_COOKIE_NAME];
  return verifySessionToken(token, secret);
}

export function sanitizeSettingsForClient(settings: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(settings)) {
    if (SECRET_SETTINGS_KEYS.has(k)) continue;
    out[k] = v;
  }
  return out;
}

export class LoginRateLimiter {
  private failures = new Map<string, { count: number; resetAt: number }>();

  isBlocked(ip: string): { blocked: boolean; retryAfter: number } {
    const rec = this.failures.get(ip);
    if (!rec) return { blocked: false, retryAfter: 0 };
    const now = Date.now();
    if (now >= rec.resetAt) {
      this.failures.delete(ip);
      return { blocked: false, retryAfter: 0 };
    }
    if (rec.count >= 8) {
      return { blocked: true, retryAfter: Math.max(1, Math.ceil((rec.resetAt - now) / 1000)) };
    }
    return { blocked: false, retryAfter: 0 };
  }

  recordFailure(ip: string): void {
    const now = Date.now();
    const rec = this.failures.get(ip);
    if (!rec || now >= rec.resetAt) {
      this.failures.set(ip, { count: 1, resetAt: now + 5 * 60_000 });
    } else {
      rec.count += 1;
    }
  }

  clear(ip: string): void {
    this.failures.delete(ip);
  }
}

export function resolveSafeAssetPath(baseDir: string, relativePath: string): string | null {
  const normalized = path.resolve(baseDir, relativePath);
  if (!normalized.startsWith(path.resolve(baseDir))) return null;
  return normalized;
}
