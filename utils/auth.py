"""
Authentication backend for Conference Room Manager — Supabase edition.

Supported sign-in methods:
  - Email + Password
  - Email OTP     (SMTP — Zoho SMTP / any SMTP)
  - Phone OTP     (Twilio — demo mode if credentials absent)
  - Google OAuth2 (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)
  - Zoho OAuth2   (ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET)

Required env / Streamlit secrets:
  SUPABASE_URL / SUPABASE_KEY
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM
  TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER  (optional)
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET                      (optional)
  ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET                         (optional)
  SESSION_TTL_HOURS  (default 24)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import secrets
import smtplib
import string
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client as _SupabaseClient

# ── Load .env files (local dev) ────────────────────────────────────────────────

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(Path(_ROOT).parent / ".env.shared")
load_dotenv(Path(_ROOT) / ".env", override=True)

OTP_EXPIRY_MIN = 10
SESSION_TTL_H  = int(os.getenv("SESSION_TTL_HOURS", "24"))


# ── Supabase client (lazy singleton) ──────────────────────────────────────────

_client: Optional[_SupabaseClient] = None


def _sb() -> _SupabaseClient:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in secrets or .env")
        _client = create_client(url, key)
    return _client


# ── Row helper ─────────────────────────────────────────────────────────────────

def _safe(row: Dict) -> Dict:
    d = dict(row)
    d.pop("password_hash", None)
    return d


# ── Schema / migration stubs (schema lives in Supabase SQL editor) ─────────────

def init_auth_db(path: str | None = None) -> None:
    pass


def migrate_auth_db(path: str | None = None) -> None:
    pass


# ── Admin flags ────────────────────────────────────────────────────────────────

def sync_admin_flags(path: str | None = None) -> None:
    raw = os.getenv("ADMIN_EMPLOYEE_IDS", "").strip()
    if not raw:
        return
    ids = [e.strip() for e in raw.split(",") if e.strip()]
    for emp_id in ids:
        try:
            _sb().table("users").update({"is_admin": 1}).eq("employee_id", emp_id).execute()
        except Exception:
            pass


# ── Employee seeding ──────────────────────────────────────────────────────────

def seed_employee(
    employee_id:  str,
    name:         str,
    branch:       str = "",
    department:   str = "",
    designation:  str = "",
    path: str | None = None,
) -> None:
    employee_id = employee_id.strip().upper()
    if not employee_id or not name:
        return
    existing = _sb().table("users").select("id").eq("employee_id", employee_id).limit(1).execute()
    if existing.data:
        return
    user_id = secrets.token_hex(16)
    dk, salt = _hash_pw(employee_id)
    pw_stored = f"{salt}:{dk}"
    try:
        _sb().table("users").insert({
            "id":                   user_id,
            "employee_id":          employee_id,
            "name":                 name,
            "branch":               branch.strip(),
            "department":           department.strip(),
            "designation":          designation.strip(),
            "password_hash":        pw_stored,
            "must_change_password": 1,
            "created_at":           datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass


# ── User helpers ───────────────────────────────────────────────────────────────

def get_user(field: str, value: str, path: str | None = None) -> Optional[Dict]:
    allowed = {"id", "employee_id", "email", "phone", "google_id", "zoho_id"}
    if field not in allowed:
        raise ValueError(f"field must be one of {allowed}")
    result = _sb().table("users").select("*").eq(field, value).eq("is_active", 1).limit(1).execute()
    return _safe(result.data[0]) if result.data else None


def update_user(
    user_id: str,
    fields:  Dict[str, Any],
    path: str | None = None,
) -> Dict[str, Any]:
    allowed = {"name", "email", "phone", "password"}
    updates: Dict[str, Any] = {}

    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        v = str(v).strip()
        if not v:
            continue
        if k == "password":
            salt   = secrets.token_hex(16)
            hashed = hashlib.pbkdf2_hmac("sha256", v.encode(), salt.encode(), 260_000)
            updates["password_hash"] = salt + ":" + hashed.hex()
        else:
            updates[k] = v.lower() if k == "email" else v

    if not updates:
        return {"error": "Nothing to update."}

    for col in ("email", "phone"):
        if col not in updates:
            continue
        clash = _sb().table("users").select("id").eq(col, updates[col]).eq("is_active", 1).neq("id", user_id).limit(1).execute()
        if clash.data:
            return {"error": f"That {col} is already registered to another account."}

    result = _sb().table("users").update(updates).eq("id", user_id).execute()
    if result.data:
        return {"success": True, "user": _safe(result.data[0])}
    return {"error": "User not found."}


def _touch(user_id: str, path: str | None = None) -> None:
    try:
        _sb().table("users").update({"last_login": datetime.now().isoformat()}).eq("id", user_id).execute()
    except Exception:
        pass


# ── Session management ─────────────────────────────────────────────────────────

def create_session(user_id: str, path: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    exp   = (datetime.now() + timedelta(hours=SESSION_TTL_H)).isoformat()
    try:
        _sb().table("sessions").delete().eq("user_id", user_id).lt("expires_at", datetime.now().isoformat()).execute()
    except Exception:
        pass
    _sb().table("sessions").insert({
        "token":      token,
        "user_id":    user_id,
        "expires_at": exp,
        "created_at": datetime.now().isoformat(),
    }).execute()
    return token


def get_user_by_session(token: str | None, path: str | None = None) -> Optional[Dict]:
    if not token:
        return None
    now = datetime.now().isoformat()
    sess = _sb().table("sessions").select("user_id, expires_at").eq("token", token).gt("expires_at", now).limit(1).execute()
    if not sess.data:
        return None
    user_id = sess.data[0]["user_id"]
    result  = _sb().table("users").select("*").eq("id", user_id).eq("is_active", 1).limit(1).execute()
    return _safe(result.data[0]) if result.data else None


def logout_session(token: str | None, path: str | None = None) -> None:
    if not token:
        return
    try:
        _sb().table("sessions").delete().eq("token", token).execute()
    except Exception:
        pass


# ── Password helpers ───────────────────────────────────────────────────────────

def verify_password(plain: str, stored_hash: str) -> bool:
    return _verify_pw(plain, stored_hash)


def _hash_pw(password: str, salt: str = "") -> Tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return dk.hex(), salt


def _verify_pw(password: str, stored: str) -> bool:
    try:
        salt, pw_hash = stored.split(":", 1)
    except ValueError:
        return False
    dk, _ = _hash_pw(password, salt)
    return hmac.compare_digest(dk, pw_hash)


# ── OTP helpers ────────────────────────────────────────────────────────────────

def _gen_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def _store_otp(identifier: str, code: str, purpose: str = "login",
               path: str | None = None) -> None:
    exp = (datetime.now() + timedelta(minutes=OTP_EXPIRY_MIN)).isoformat()
    try:
        _sb().table("otp_codes").update({"used": 1}).eq("identifier", identifier).eq("purpose", purpose).eq("used", 0).execute()
    except Exception:
        pass
    _sb().table("otp_codes").insert({
        "identifier": identifier,
        "code":       code,
        "purpose":    purpose,
        "expires_at": exp,
        "used":       0,
        "created_at": datetime.now().isoformat(),
    }).execute()


def _verify_otp_code(identifier: str, code: str, purpose: str = "login",
                     path: str | None = None) -> Dict[str, Any]:
    result = _sb().table("otp_codes").select("*").eq("identifier", identifier).eq("code", code).eq("purpose", purpose).eq("used", 0).order("created_at", desc=True).limit(1).execute()
    if not result.data:
        return {"error": "Invalid OTP. Please try again."}
    row = result.data[0]
    if datetime.fromisoformat(row["expires_at"]) < datetime.now():
        return {"error": "OTP has expired. Please request a new one."}
    try:
        _sb().table("otp_codes").update({"used": 1}).eq("id", row["id"]).execute()
    except Exception:
        pass
    return {"ok": True}


# ── Registration ───────────────────────────────────────────────────────────────

def register_user(
    name:        str,
    employee_id: str,
    email:       str = "",
    phone:       str = "",
    password:    str = "",
    path: str | None = None,
) -> Dict[str, Any]:
    name        = name.strip()
    employee_id = employee_id.strip().upper()
    email       = email.strip().lower() or None
    phone       = phone.strip() or None

    if not name:
        return {"error": "Full name is required."}
    if not employee_id:
        return {"error": "Employee ID is required."}
    if not email and not phone:
        return {"error": "At least one of email or phone is required."}

    pw_stored = None
    if password:
        dk, salt  = _hash_pw(password)
        pw_stored = f"{salt}:{dk}"

    existing = get_user("employee_id", employee_id)
    if existing:
        has_contact = existing.get("email") or existing.get("phone")
        if has_contact:
            return {"error": "This Employee ID is already registered. Please sign in instead."}

        updates: Dict[str, Any] = {}
        if email:
            clash = get_user("email", email)
            if clash and clash["id"] != existing["id"]:
                return {"error": "This email is already used by another account."}
            updates["email"] = email
        if phone:
            clash = get_user("phone", phone)
            if clash and clash["id"] != existing["id"]:
                return {"error": "This phone number is already used by another account."}
            updates["phone"] = phone
        if pw_stored:
            updates["password_hash"] = pw_stored
        if name and name != existing.get("name", ""):
            updates["name"] = name

        if updates:
            _sb().table("users").update(updates).eq("id", existing["id"]).execute()

        _touch(existing["id"])
        user  = get_user("id", existing["id"])
        token = create_session(existing["id"])
        return {"success": True, "user": user, "token": token, "activated": True}

    user_id = secrets.token_hex(16)
    try:
        _sb().table("users").insert({
            "id":           user_id,
            "employee_id":  employee_id,
            "name":         name,
            "email":        email,
            "phone":        phone,
            "password_hash": pw_stored,
            "created_at":   datetime.now().isoformat(),
        }).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "email" in msg:
            return {"error": "This email is already registered."}
        if "phone" in msg:
            return {"error": "This phone number is already registered."}
        return {"error": f"Registration failed: {exc}"}

    user  = get_user("id", user_id)
    token = create_session(user_id)
    return {"success": True, "user": user, "token": token}


def complete_oauth_registration(
    name:        str,
    employee_id: str,
    email:       str = "",
    phone:       str = "",
    google_id:   str = "",
    zoho_id:     str = "",
    path: str | None = None,
) -> Dict[str, Any]:
    name        = name.strip()
    employee_id = employee_id.strip().upper()
    email       = email.strip().lower() or None
    phone       = phone.strip() or None

    if not name or not employee_id:
        return {"error": "Full name and Employee ID are required."}

    user_id = secrets.token_hex(16)
    try:
        _sb().table("users").insert({
            "id":          user_id,
            "employee_id": employee_id,
            "name":        name,
            "email":       email,
            "phone":       phone,
            "google_id":   google_id or None,
            "zoho_id":     zoho_id   or None,
            "created_at":  datetime.now().isoformat(),
        }).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "employee_id" in msg:
            return {"error": "Employee ID is already registered."}
        if "email" in msg:
            return {"error": "This email is already registered."}
        return {"error": f"Registration failed: {exc}"}

    _touch(user_id)
    user  = get_user("id", user_id)
    token = create_session(user_id)
    return {"success": True, "user": user, "token": token}


# ── Password login ─────────────────────────────────────────────────────────────

def login_password(identifier: str, password: str,
                   path: str | None = None) -> Dict[str, Any]:
    identifier = identifier.strip()
    user = get_user("email", identifier.lower())
    if not user:
        user = get_user("employee_id", identifier.upper())
    if not user:
        return {"error": "No account found with that email or Employee ID."}

    stored = _raw_pw(user["id"])
    if not stored:
        return {"error": "This account has no password set. "
                         "Please sign in with OTP, Google, or Zoho."}
    if not _verify_pw(password, stored):
        return {"error": "Incorrect password."}

    _touch(user["id"])
    token = create_session(user["id"])
    return {"success": True, "user": user, "token": token}


def _raw_pw(user_id: str, path: str | None = None) -> str:
    result = _sb().table("users").select("password_hash").eq("id", user_id).limit(1).execute()
    return (result.data[0].get("password_hash") or "") if result.data else ""


# ── Email OTP ──────────────────────────────────────────────────────────────────

def send_email_otp(email: str, path: str | None = None) -> Dict[str, Any]:
    email = email.strip().lower()
    if not get_user("email", email):
        return {"error": "No account found with this email. Please register first."}

    otp  = _gen_otp()
    _store_otp(email, otp, "login")

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pw   = os.getenv("SMTP_PASS", "")
    frm  = os.getenv("SMTP_FROM", user)

    if not user or not pw:
        print(f"[AUTH DEMO] Email OTP for {email}: {otp}  (expires {OTP_EXPIRY_MIN} min)")
        return {"success": True, "demo": True, "otp": otp}

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = "Your sign-in OTP — Conference Room Manager"
    msg["From"]    = frm
    msg["To"]      = email
    html = f"""<html><body style="font-family:DM Sans,sans-serif;max-width:480px;
        margin:40px auto;padding:0 20px">
      <div style="border-radius:20px;background:#040e1f;padding:32px 28px">
        <p style="color:#00AFEF;font-weight:700;letter-spacing:.12em;
                  text-transform:uppercase;font-size:.82rem;margin:0 0 8px">
          Rite Water Solutions
        </p>
        <h2 style="color:#f7f4ed;margin:0 0 20px;font-size:1.5rem">
          Your sign-in code
        </h2>
        <div style="background:#0d1f3c;border-radius:14px;padding:20px;
                    text-align:center;font-size:2.4rem;font-weight:700;
                    letter-spacing:.35em;color:#00AFEF;margin-bottom:20px">
          {otp}
        </div>
        <p style="color:#8fa8c8;font-size:.9rem;margin:0">
          Expires in {OTP_EXPIRY_MIN} minutes. Do not share this code.
        </p>
      </div>
    </body></html>"""
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo(); s.starttls(); s.login(user, pw)
            s.sendmail(frm, email, msg.as_string())
        return {"success": True}
    except Exception as exc:
        return {"error": str(exc)}


def login_email_otp(email: str, code: str,
                    path: str | None = None) -> Dict[str, Any]:
    email = email.strip().lower()
    res   = _verify_otp_code(email, code, "login")
    if res.get("error"):
        return res
    user = get_user("email", email)
    if not user:
        return {"error": "No account found for this email."}
    _touch(user["id"])
    token = create_session(user["id"])
    return {"success": True, "user": user, "token": token}


# ── Phone OTP ──────────────────────────────────────────────────────────────────

def send_phone_otp(phone: str, path: str | None = None) -> Dict[str, Any]:
    phone = phone.strip()
    if not get_user("phone", phone):
        return {"error": "No account found with this phone number. Please register first."}

    otp = _gen_otp()
    _store_otp(phone, otp, "login")

    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    tok = os.getenv("TWILIO_AUTH_TOKEN", "")
    frm = os.getenv("TWILIO_FROM_NUMBER", "")

    if not sid or not tok or sid.startswith("AC" + "x"):
        print(f"[AUTH DEMO] SMS OTP for {phone}: {otp}  (expires {OTP_EXPIRY_MIN} min)")
        return {"success": True, "demo": True, "otp": otp}

    try:
        from twilio.rest import Client  # type: ignore
        Client(sid, tok).messages.create(
            body=f"Conference Rooms OTP: {otp} (valid {OTP_EXPIRY_MIN} min). Do not share.",
            from_=frm, to=phone,
        )
        return {"success": True}
    except ImportError:
        print(f"[AUTH DEMO] Twilio not installed. SMS OTP for {phone}: {otp}")
        return {"success": True, "demo": True, "otp": otp}
    except Exception as exc:
        return {"error": str(exc)}


def login_phone_otp(phone: str, code: str,
                    path: str | None = None) -> Dict[str, Any]:
    phone = phone.strip()
    res   = _verify_otp_code(phone, code, "login")
    if res.get("error"):
        return res
    user = get_user("phone", phone)
    if not user:
        return {"error": "No account found for this phone number."}
    _touch(user["id"])
    token = create_session(user["id"])
    return {"success": True, "user": user, "token": token}


# ── Google OAuth2 ──────────────────────────────────────────────────────────────

def google_auth_url(redirect_uri: str, theme: str = "Dark") -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id:
        return ""
    safe_theme = theme if theme in ("Dark", "Light", "System") else "Dark"
    state  = f"google_{safe_theme}_{secrets.token_urlsafe(12)}"
    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "prompt":        "select_account",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def google_callback(code: str, redirect_uri: str,
                    path: str | None = None) -> Dict[str, Any]:
    client_id     = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return {"error": "Google OAuth is not configured on this server."}

    body = urllib.parse.urlencode({
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as r:
            token_info = json.loads(r.read())
    except Exception as exc:
        return {"error": f"Google token exchange failed: {exc}"}

    access_token = token_info.get("access_token")
    if not access_token:
        return {"error": f"Google returned no access token. Response: {token_info}"}

    try:
        req = urllib.request.Request("https://www.googleapis.com/oauth2/v2/userinfo")
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, timeout=15) as r:
            ginfo = json.loads(r.read())
    except Exception as exc:
        return {"error": f"Google userinfo fetch failed: {exc}"}

    google_id = ginfo.get("id", "")
    email     = (ginfo.get("email") or "").strip().lower()
    name      = ginfo.get("name", "")

    user = (get_user("google_id", google_id) if google_id else None) or \
           (get_user("email",     email)     if email     else None)
    if user:
        if not user.get("google_id") and google_id:
            _sb().table("users").update({"google_id": google_id}).eq("id", user["id"]).execute()
        _touch(user["id"])
        token = create_session(user["id"])
        return {"success": True, "user": user, "token": token}

    return {"success": True, "new_user": True, "google_id": google_id, "email": email, "name": name}


# ── Zoho OAuth2 ────────────────────────────────────────────────────────────────

def zoho_auth_url(redirect_uri: str, theme: str = "Dark") -> str:
    client_id = os.getenv("ZOHO_CLIENT_ID", "")
    if not client_id:
        return ""
    safe_theme = theme if theme in ("Dark", "Light", "System") else "Dark"
    state  = f"zoho_{safe_theme}_{secrets.token_urlsafe(12)}"
    base   = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in")
    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "ZohoMail.accounts.READ",
        "state":         state,
        "access_type":   "offline",
        "prompt":        "consent",
    })
    return f"{base}/oauth/v2/auth?{params}"


def zoho_callback(code: str, redirect_uri: str,
                  path: str | None = None) -> Dict[str, Any]:
    client_id     = os.getenv("ZOHO_CLIENT_ID", "")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
    base          = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in")
    if not client_id or not client_secret:
        return {"error": "Zoho OAuth is not configured on this server."}

    body = urllib.parse.urlencode({
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    try:
        req = urllib.request.Request(f"{base}/oauth/v2/token", data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as r:
            token_info = json.loads(r.read())
    except Exception as exc:
        return {"error": f"Zoho token exchange failed: {exc}"}

    access_token = token_info.get("access_token")
    if not access_token:
        return {"error": f"Zoho returned no access token. Response: {token_info}"}

    zoho_api = os.getenv("ZOHO_MAIL_API", "https://mail.zoho.in")
    try:
        req = urllib.request.Request(f"{zoho_api}/api/accounts")
        req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")
        with urllib.request.urlopen(req, timeout=15) as r:
            zdata = json.loads(r.read())
    except Exception as exc:
        return {"error": f"Zoho account info fetch failed: {exc}"}

    accs = zdata.get("data", [])
    if not accs:
        return {"error": "No Zoho mail accounts found for this user."}

    acc     = accs[0]
    zoho_id = str(acc.get("accountId", ""))
    name    = acc.get("displayName", "")

    email_raw = acc.get("emailAddress") or ""
    if isinstance(email_raw, list):
        if email_raw and isinstance(email_raw[0], dict):
            primary = next((e for e in email_raw if e.get("isPrimary")), email_raw[0])
            email   = (primary.get("mailId") or primary.get("mail") or "").strip().lower()
        else:
            email = (email_raw[0] if email_raw else "").strip().lower()
    else:
        email = email_raw.strip().lower()

    user = (get_user("zoho_id", zoho_id) if zoho_id else None) or \
           (get_user("email",   email)   if email   else None)
    if user:
        if not user.get("zoho_id") and zoho_id:
            _sb().table("users").update({"zoho_id": zoho_id}).eq("id", user["id"]).execute()
        _touch(user["id"])
        token = create_session(user["id"])
        return {"success": True, "user": user, "token": token}

    return {"success": True, "new_user": True, "zoho_id": zoho_id, "email": email, "name": name}
