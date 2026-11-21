"""FrimeRise Security & Remote Access Layer (Tailscale-ready).

Zero third-party dependencies (100% Python standard library — PSF license).
Provides:
  - Salted PBKDF2-HMAC-SHA256 password hashing & constant-time verification
  - HMAC-SHA256 signed HttpOnly session cookies (__Host- on HTTPS, fallback on HTTP)
  - Strict local vs. remote/proxy request detection (Tailscale Serve aware)
  - Per-IP sliding-window brute-force rate limiter for login
  - Settings sanitizer (never leaks password hashes or signing secrets to the UI)
  - Non-privileged Tailscale status probe (detects tailnet connection & MagicDNS HTTPS URL)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import shutil
import subprocess
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from fastapi import Request

from database import get_settings, save_settings

HTTPS_COOKIE_NAME = "__Host-frimerise_session"
HTTP_COOKIE_NAME = "frimerise_session"
CSRF_COOKIE_NAME = "frimerise_login_csrf"
SESSION_TTL_SECONDS = 14 * 24 * 3600  # 14 days
PBKDF2_ITERATIONS = 260_000

_PROXY_HEADERS = (
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "forwarded",
    "tailscale-user-login",
    "tailscale-user-name",
    "tailscale-user-profile-pic",
    "cf-connecting-ip",
    "true-client-ip",
)

_SENSITIVE_SETTING_KEYS = (
    "auth_password_hash",
    "auth_session_secret",
)


# ---------------------------------------------------------------------------
# Password Hashing (PBKDF2-HMAC-SHA256 + 128-bit random salt)
# ---------------------------------------------------------------------------
def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    try:
        algo, iters_s, salt_hex, hash_hex = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def generate_readable_password() -> str:
    """Generate a high-entropy readable password (no ambiguous 0/O/1/l/I chars)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return f"Frime-{parts[0]}-{parts[1]}-{parts[2]}"


# ---------------------------------------------------------------------------
# Session Tokens (HMAC-SHA256 signed payload)
# ---------------------------------------------------------------------------
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    pad = "=" * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(encoded + pad)


def create_session_token(username: str, secret: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    exp = int(time.time()) + int(ttl_seconds)
    nonce = secrets.token_hex(8)
    payload = json.dumps({"u": username, "exp": exp, "n": nonce}, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload)
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def verify_session_token(token: str, secret: str, expected_username: Optional[str] = None) -> Optional[str]:
    if not token or not secret or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        data = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        username = str(data.get("u") or "")
        if not username:
            return None
        if expected_username and not hmac.compare_digest(username, expected_username):
            return None
        return username
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Auth Config Storage (SQLite settings table)
# ---------------------------------------------------------------------------
def ensure_auth_secret(settings: Optional[Dict[str, str]] = None) -> str:
    s = settings if settings is not None else get_settings()
    secret = (s.get("auth_session_secret") or "").strip()
    if len(secret) >= 32:
        return secret
    secret = secrets.token_hex(32)
    save_settings({"auth_session_secret": secret})
    return secret


def bootstrap_initial_credentials_if_missing(default_username: str = "frimerise") -> Tuple[str, Optional[str]]:
    """Ensure auth_username, auth_session_secret, and auth_password_hash exist.

    Returns (username, generated_plaintext_password_or_None).
    Plaintext is ONLY returned on initial generation and never stored on disk.
    """
    s = get_settings()
    username = (s.get("auth_username") or default_username).strip() or default_username
    updates: Dict[str, str] = {}
    if not s.get("auth_username"):
        updates["auth_username"] = username
    if not s.get("auth_session_secret") or len(s.get("auth_session_secret", "")) < 32:
        updates["auth_session_secret"] = secrets.token_hex(32)
    if "auth_require_local" not in s:
        updates["auth_require_local"] = "0"

    generated_pw: Optional[str] = None
    if not (s.get("auth_password_hash") or "").strip():
        generated_pw = generate_readable_password()
        updates["auth_password_hash"] = hash_password(generated_pw)

    if updates:
        save_settings(updates)
    return username, generated_pw


def update_remote_credentials(
    *,
    username: Optional[str] = None,
    new_password: Optional[str] = None,
    require_local: Optional[bool] = None,
) -> Dict[str, Any]:
    s = get_settings()
    updates: Dict[str, str] = {}

    if username is not None:
        clean_user = username.strip()
        if len(clean_user) < 2 or len(clean_user) > 64:
            raise ValueError("Usuário deve ter entre 2 e 64 caracteres.")
        updates["auth_username"] = clean_user

    password_rotated = False
    if new_password is not None and new_password != "":
        if len(new_password) < 8:
            raise ValueError("A senha deve ter no mínimo 8 caracteres.")
        updates["auth_password_hash"] = hash_password(new_password)
        # Rotate signing key to immediately revoke all previously issued cookies
        updates["auth_session_secret"] = secrets.token_hex(32)
        password_rotated = True

    if require_local is not None:
        updates["auth_require_local"] = "1" if require_local else "0"

    if updates:
        s = save_settings(updates)

    return {
        "auth_configured": bool((s.get("auth_password_hash") or "").strip()),
        "auth_username": s.get("auth_username") or "frimerise",
        "auth_require_local": s.get("auth_require_local") == "1",
        "password_rotated": password_rotated,
    }


def sanitize_settings_for_client(settings: Dict[str, str]) -> Dict[str, Any]:
    """Return settings dictionary safe for browser JSON (strips password hash & HMAC secret)."""
    cleaned: Dict[str, Any] = {
        k: v for k, v in settings.items() if k not in _SENSITIVE_SETTING_KEYS
    }
    cleaned["auth_configured"] = bool((settings.get("auth_password_hash") or "").strip())
    cleaned["auth_username"] = settings.get("auth_username") or "frimerise"
    cleaned["auth_require_local"] = settings.get("auth_require_local") == "1"
    return cleaned


# ---------------------------------------------------------------------------
# Request Classification (Localhost vs. Tailscale / Remote)
# ---------------------------------------------------------------------------
def is_https_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https"


def _extract_host_without_port(host_header: str) -> str:
    raw = (host_header or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end != -1 else raw
    return raw.split(":", 1)[0]


def is_direct_local_request(request: Request) -> bool:
    """True ONLY for unproxied loopback requests to localhost/127.0.0.1/::1.

    Requests proxied through `tailscale serve` arrive on 127.0.0.1 but carry
    a `*.ts.net` Host header and `X-Forwarded-*` / `Tailscale-User-*` headers,
    so they are strictly treated as REMOTE and require authentication.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        return False

    for header in _PROXY_HEADERS:
        if request.headers.get(header):
            return False

    host_only = _extract_host_without_port(request.headers.get("host") or "")
    if host_only not in ("localhost", "127.0.0.1", "::1"):
        return False

    return True


def get_client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "unknown"


def sanitize_next_url(next_url: Optional[str]) -> str:
    """Prevent open redirects: allow ONLY relative local paths starting with a single '/'."""
    raw = (next_url or "/").strip()
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return "/"
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return "/"
    return raw


def extract_authenticated_user(request: Request, settings: Dict[str, str]) -> Optional[str]:
    """Validate session cookie (preferred) or HTTP Basic Auth header."""
    expected_user = (settings.get("auth_username") or "frimerise").strip()
    pw_hash = (settings.get("auth_password_hash") or "").strip()
    secret = (settings.get("auth_session_secret") or "").strip()

    if not pw_hash:
        return None

    # 1. Signed HttpOnly session cookie
    if secret:
        cookie_token: Optional[str] = None
        if is_https_request(request):
            cookie_token = request.cookies.get(HTTPS_COOKIE_NAME)
        else:
            cookie_token = request.cookies.get(HTTPS_COOKIE_NAME) or request.cookies.get(HTTP_COOKIE_NAME)
        if cookie_token:
            verified_user = verify_session_token(cookie_token, secret, expected_username=expected_user)
            if verified_user:
                return verified_user

    # 2. HTTP Basic Auth fallback (useful for curl/API scripts over Tailscale)
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            user, pwd = decoded.split(":", 1)
            if hmac.compare_digest(user, expected_user) and verify_password(pwd, pw_hash):
                return expected_user
        except Exception:
            return None

    return None


# ---------------------------------------------------------------------------
# Login Brute-Force Rate Limiter (in-memory sliding window per client IP)
# ---------------------------------------------------------------------------
class LoginRateLimiter:
    def __init__(self, max_attempts: int = 10, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: Dict[str, List[float]] = defaultdict(list)

    def _prune(self, key: str, now: float) -> List[float]:
        cutoff = now - self.window_seconds
        recent = [ts for ts in self._failures.get(key, []) if ts >= cutoff]
        self._failures[key] = recent
        return recent

    def is_blocked(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        recent = self._prune(key, now)
        if len(recent) >= self.max_attempts:
            retry_after = max(1, int(self.window_seconds - (now - recent[0])))
            return True, retry_after
        return False, 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        recent = self._prune(key, now)
        recent.append(now)
        self._failures[key] = recent

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)


LOGIN_RATE_LIMITER = LoginRateLimiter(max_attempts=10, window_seconds=300)


# ---------------------------------------------------------------------------
# Tailscale Status Probe (Read-Only, Zero Sudo)
# ---------------------------------------------------------------------------
def probe_tailscale_status() -> Dict[str, Any]:
    """Inspect local Tailscale installation, tailnet IP, and MagicDNS HTTPS URL."""
    ts_bin = shutil.which("tailscale")
    result: Dict[str, Any] = {
        "installed": ts_bin is not None,
        "connected": False,
        "backend_state": "NotInstalled" if ts_bin is None else "Unknown",
        "hostname": "",
        "dns_name": "",
        "tailscale_ip": "",
        "https_url": "",
        "serve_configured": False,
        "setup_command": "./setup_tailscale.sh",
    }
    if not ts_bin:
        return result

    try:
        proc = subprocess.run(
            [ts_bin, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            state = str(data.get("BackendState") or "")
            result["backend_state"] = state
            self_node = data.get("Self") or {}
            ips = self_node.get("TailscaleIPs") or []
            ipv4 = next((ip for ip in ips if "." in str(ip)), ips[0] if ips else "")
            dns_name = str(self_node.get("DNSName") or "").rstrip(".")
            result["hostname"] = str(self_node.get("HostName") or "")
            result["dns_name"] = dns_name
            result["tailscale_ip"] = str(ipv4)
            result["connected"] = state == "Running" and bool(ipv4)
            if dns_name and result["connected"]:
                result["https_url"] = f"https://{dns_name}"
    except Exception:
        pass

    if result["connected"]:
        try:
            serve_proc = subprocess.run(
                [ts_bin, "serve", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if serve_proc.returncode == 0 and "8000" in (serve_proc.stdout or ""):
                result["serve_configured"] = True
        except Exception:
            pass

    return result
