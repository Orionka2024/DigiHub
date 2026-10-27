import logging
import os
import json
import jwt
import hashlib
import secrets
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel
from typing import Optional, Tuple, Dict, Any

# JWT configuration
_DEV_SECRET = "dev-secret-key-change-me-in-production"
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", _DEV_SECRET)
if (SECRET_KEY == _DEV_SECRET or len(SECRET_KEY) < 32) and (os.environ.get("VERCEL") or os.environ.get("PROD") == "1"):
    raise RuntimeError("Set a private JWT_SECRET_KEY before starting production.")
if SECRET_KEY == _DEV_SECRET:
    logging.warning(
        "[AUTH] JWT_SECRET_KEY is not set — using insecure development default. "
        "Set JWT_SECRET_KEY in Vercel Environment Variables before accepting real users."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

# Detect HTTPS deployment (Vercel always serves HTTPS)
_SECURE_COOKIE = os.environ.get("VERCEL") == "1" or os.environ.get("SECURE_COOKIE", "").lower() == "true"

auth_router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

def hash_password(password: str) -> str:
    """Create a pbkdf2_hmac password hash (format: salt:hash)."""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{key.hex()}"

def is_pbkdf2_hash(val: str) -> bool:
    """Check if value is already a formatted PBKDF2 salt:hash."""
    if not val or ":" not in val:
        return False
    parts = val.split(":", 1)
    if len(parts) != 2:
        return False
    try:
        bytes.fromhex(parts[0])
        bytes.fromhex(parts[1])
        return len(parts[0]) == 32 and len(parts[1]) == 64
    except Exception:
        return False

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a pbkdf2_hmac password hash (format: salt:hash). Rejects plaintext and placeholders."""
    if not hashed_password or not plain_password:
        return False
    if hashed_password == "supabase_auth":
        return False
    try:
        if ":" in hashed_password:
            salt_hex, hash_hex = hashed_password.split(":", 1)
            salt = bytes.fromhex(salt_hex)
            key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100000)
            return secrets.compare_digest(key.hex(), hash_hex)
    except Exception:
        pass
    return False

def get_allowed_users() -> Dict[str, str]:
    """
    Load allowed users from all configured sources:
    1. ALLOWED_USERS environment variable (handles comma/semicolon/newline separation; auto-hashes plaintext)
    2. Local users.json
    3. Supabase digihub_users table
    Returns mapping of lowercase identifier (username and email) -> pwd_hash.
    """
    users: Dict[str, str] = {}

    # 1. ALLOWED_USERS environment variable
    env_users = os.environ.get("ALLOWED_USERS", "")
    if env_users:
        try:
            raw_entries = env_users.replace("\n", ",").replace(";", ",").split(",")
            for pair in raw_entries:
                pair = pair.strip().strip("'\"")
                if ":" in pair:
                    username, pwd = pair.split(":", 1)
                    u_clean = username.strip().strip("'\"").lower()
                    p_clean = pwd.strip().strip("'\"")
                    if u_clean and p_clean:
                        users[u_clean] = p_clean if is_pbkdf2_hash(p_clean) else hash_password(p_clean)
        except Exception as exc:
            logging.warning("[Auth] Error parsing ALLOWED_USERS: %s", exc)

    # 2. Local users.json fallback
    users_file = os.path.join(os.path.dirname(__file__), "..", "users.json")
    if os.path.exists(users_file):
        try:
            with open(users_file, "r") as f:
                raw_users = json.load(f)
                for k, v in raw_users.items():
                    k_clean = str(k).strip().strip("'\"").lower()
                    if k_clean not in users:
                        v_clean = str(v).strip().strip("'\"")
                        users[k_clean] = v_clean if is_pbkdf2_hash(v_clean) else hash_password(v_clean)
        except Exception:
            pass

    # 3. Supabase digihub_users table
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        if client:
            result = client.table("digihub_users").select("*").execute()
            for row in (result.data or []):
                pwd_hash = (row.get("pwd_hash") or "").strip()
                u_name = str(row["username"]).strip().strip("'\"").lower() if row.get("username") else None
                e_name = str(row["email"]).strip().strip("'\"").lower() if row.get("email") else None

                if pwd_hash and pwd_hash != "supabase_auth":
                    stored = pwd_hash if is_pbkdf2_hash(pwd_hash) else hash_password(pwd_hash)
                    if u_name:
                        users[u_name] = stored
                    if e_name:
                        users[e_name] = stored
                else:
                    if u_name and u_name not in users:
                        users[u_name] = pwd_hash
                    if e_name and e_name not in users:
                        users[e_name] = pwd_hash
    except Exception as exc:
        logging.warning("[Auth] Failed to load users from Supabase: %s", exc)

    return users

def verify_supabase_password(email: str, password: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Authenticate email + password against Supabase GoTrue token endpoint.
    Uses SUPABASE_ANON_KEY (if present) or SUPABASE_SERVICE_ROLE_KEY.
    Direct HTTP avoids gotrue-py session conflicts and service_role bearer rejection.
    Returns (user_dict, error_description).
    """
    supabase_url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    service_key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    anon_key = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    api_key = anon_key or service_key

    if not supabase_url or not api_key:
        return None, "Supabase environment variables not configured."

    url = f"{supabase_url}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    if anon_key:
        headers["Authorization"] = f"Bearer {anon_key}"

    try:
        with httpx.Client(timeout=10.0) as http:
            resp = http.post(url, headers=headers, json={"email": email, "password": password})
            if resp.status_code == 200:
                data = resp.json()
                return data.get("user") or {}, None
            else:
                err_data = {}
                try:
                    err_data = resp.json()
                except Exception:
                    pass
                err_desc = err_data.get("error_description") or err_data.get("msg") or resp.text
                logging.info("[Auth] Supabase GoTrue token returned %s: %s", resp.status_code, err_desc)
                return None, err_desc
    except Exception as exc:
        logging.warning("[Auth] Supabase auth request failed: %s", exc)
        return None, str(exc)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@auth_router.post("/api/login")
def login(login_data: LoginRequest, response: Response):
    identifier = login_data.username.strip().lower()
    password = login_data.password
    authenticated_user = None

    # 1. Check ALLOWED_USERS / users.json / digihub_users
    users = get_allowed_users()
    stored_hash = users.get(identifier)
    if stored_hash and verify_password(password, stored_hash):
        authenticated_user = identifier

    # 2. Check Supabase Auth
    if not authenticated_user:
        user_obj, err_msg = verify_supabase_password(identifier, password)
        if user_obj:
            authenticated_user = (user_obj.get("email") or identifier).lower()
        else:
            # Check Supabase admin for detailed diagnosis & auto-confirmation
            try:
                from app.supabase_client import get_supabase
                client = get_supabase()
                if client:
                    target_u = None
                    try:
                        for u in client.auth.admin.list_users():
                            if u.email and u.email.strip().lower() == identifier:
                                target_u = u
                                break
                    except Exception as list_err:
                        logging.warning("[Auth] Failed to list Supabase users: %s", list_err)

                    if target_u:
                        # Auto-confirm if not confirmed
                        if not getattr(target_u, "email_confirmed_at", None):
                            try:
                                client.auth.admin.update_user_by_id(target_u.id, {"email_confirm": True})
                                logging.info("[Auth] Auto-confirmed email for Supabase user %s", identifier)
                                # Retry password verification after confirmation
                                retry_obj, _ = verify_supabase_password(identifier, password)
                                if retry_obj:
                                    authenticated_user = (retry_obj.get("email") or identifier).lower()
                            except Exception as confirm_err:
                                logging.warning("[Auth] Auto-confirm failed: %s", confirm_err)

                        # Also try supabase-py client as fallback
                        if not authenticated_user:
                            try:
                                from app.supabase_client import new_auth_client
                                auth_resp = new_auth_client().auth.sign_in_with_password({
                                    "email": identifier,
                                    "password": password
                                })
                                if auth_resp and getattr(auth_resp, "user", None):
                                    authenticated_user = (getattr(auth_resp.user, "email", None) or identifier).lower()
                            except Exception:
                                pass

                        if not authenticated_user:
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail=f"Invalid password for '{identifier}'. Please check your password in the Supabase Dashboard (Authentication -> Users) or configure ALLOWED_USERS in Vercel."
                            )
            except HTTPException:
                raise
            except Exception as admin_err:
                logging.warning("[Auth] Supabase admin lookup error: %s", admin_err)

    # 3. If still not authenticated:
    if not authenticated_user:
        if identifier in users:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid password for '{identifier}'.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User '{identifier}' not found in Supabase Auth or ALLOWED_USERS. Please check the email entered or configure ALLOWED_USERS in Vercel.",
        )

    # Sync authenticated user to digihub_users table if not present (best-effort)
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        if client:
            try:
                existing = client.table("digihub_users").select("id").eq("username", authenticated_user).execute()
                if not existing.data:
                    client.table("digihub_users").insert({
                        "username": authenticated_user,
                        "email": authenticated_user if "@" in authenticated_user else None,
                        "pwd_hash": "supabase_auth",
                        "role": "preparer"
                    }).execute()
            except Exception:
                pass
    except Exception:
        pass

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": authenticated_user}, expires_delta=access_token_expires
    )

    # Set HTTP-only cookie; Secure flag is enabled on HTTPS/Vercel deployments
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=_SECURE_COOKIE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/"
    )

    return {"message": "Login successful", "user": authenticated_user}

@auth_router.get("/api/auth/diagnostic")
def auth_diagnostic():
    """Diagnostic endpoint to inspect Supabase connection and configured auth providers."""
    diag = {
        "has_jwt_secret": bool(os.environ.get("JWT_SECRET_KEY")),
        "has_supabase_url": bool(os.environ.get("SUPABASE_URL")),
        "has_service_role_key": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
        "has_anon_key": bool(os.environ.get("SUPABASE_ANON_KEY")),
        "has_allowed_users_env": bool(os.environ.get("ALLOWED_USERS")),
        "allowed_user_identifiers": list(get_allowed_users().keys()),
        "supabase_auth_users": []
    }
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        if client:
            users = client.auth.admin.list_users()
            diag["supabase_auth_users"] = [
                {
                    "email": u.email,
                    "confirmed": bool(u.email_confirmed_at),
                    "created_at": str(u.created_at) if u.created_at else None,
                    "last_sign_in_at": str(u.last_sign_in_at) if u.last_sign_in_at else None,
                }
                for u in (users or [])
            ]
    except Exception as exc:
        diag["supabase_auth_error"] = str(exc)

    return diag

@auth_router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}

def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    
    if not token:
        raise credentials_exception
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise credentials_exception
        return username.lower()
    except jwt.PyJWTError:
        raise credentials_exception


def get_user_role(username):
    """Roles are assigned by the operator, never supplied by a browser."""
    if os.environ.get("SUPABASE_URL"):
        from app.supabase_client import get_supabase
        rows = get_supabase().table("digihub_users").select("username,email,role").execute().data
        roles = [r.get("role", "preparer") for r in rows
                 if username in (str(r.get("username", "")).lower(), str(r.get("email", "")).lower())]
        return roles[0] if roles else "preparer"
    return json.loads(os.environ.get("LOCAL_USER_ROLES", "{}")).get(username, "preparer")


@auth_router.get("/api/me")
def me(request: Request):
    username = get_current_user(request)
    return {"user": username, "role": get_user_role(username)}
