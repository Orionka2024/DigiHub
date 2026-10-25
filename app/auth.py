import logging
import os
import json
import jwt
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel
from typing import Optional

# JWT configuration
_DEV_SECRET = "dev-secret-key-change-me-in-production"
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", _DEV_SECRET)
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

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a pbkdf2_hmac password hash (format: salt:hash) or plaintext match."""
    if not hashed_password:
        return False
    if hashed_password == plain_password:
        return True
    try:
        salt_hex, hash_hex = hashed_password.split(':')
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt, 100000)
        return secrets.compare_digest(key.hex(), hash_hex)
    except Exception:
        return False

def get_allowed_users():
    """
    Load allowed users from Supabase digihub_users table.
    Falls back to ALLOWED_USERS env var / users.json if Supabase is unavailable.
    Returns mapping of lowercase identifier (username and email) -> pwd_hash.
    """
    users = {}
    
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        if client:
            result = client.table("digihub_users").select("*").execute()
            for row in result.data:
                pwd_hash = row.get("pwd_hash") or ""
                if row.get("username"):
                    users[str(row["username"]).strip().lower()] = pwd_hash
                if row.get("email"):
                    users[str(row["email"]).strip().lower()] = pwd_hash
            if users:
                return users
    except Exception as exc:
        logging.warning("[Auth] Failed to load users from Supabase: %s", exc)

    # Fallback for local testing if Supabase is not configured
    env_users = os.environ.get("ALLOWED_USERS")
    if env_users:
        try:
            for pair in env_users.split(","):
                if ":" in pair:
                    username, pwd = pair.split(":", 1)
                    users[username.strip().lower()] = pwd.strip()
        except Exception:
            pass
            
    if not users:
        users_file = os.path.join(os.path.dirname(__file__), "..", "users.json")
        if os.path.exists(users_file):
            try:
                with open(users_file, "r") as f:
                    raw_users = json.load(f)
                    for k, v in raw_users.items():
                        users[k.strip().lower()] = v
            except Exception:
                pass
                
    return users

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
    identifier = login_data.username.strip()
    password = login_data.password
    authenticated_user = None

    # 1. Attempt Supabase Auth (e.g. if user added via Supabase Dashboard -> Authentication -> Users)
    try:
        from app.supabase_client import get_supabase
        client = get_supabase()
        if client:
            try:
                auth_resp = client.auth.sign_in_with_password({
                    "email": identifier,
                    "password": password
                })
                if auth_resp and getattr(auth_resp, "user", None):
                    user_obj = auth_resp.user
                    authenticated_user = getattr(user_obj, "email", None) or identifier
                    # Sync to digihub_users table if not yet present
                    try:
                        existing = client.table("digihub_users").select("id").eq("username", authenticated_user).execute()
                        if not existing.data:
                            client.table("digihub_users").insert({
                                "username": authenticated_user,
                                "pwd_hash": "supabase_auth",
                                "role": "preparer"
                            }).execute()
                    except Exception:
                        pass
            except Exception as auth_err:
                logging.info("[Auth] Supabase Auth sign-in attempted for %s: %s", identifier, auth_err)
    except Exception:
        pass

    # 2. If not authenticated via Supabase Auth, verify against digihub_users table / ALLOWED_USERS / users.json
    if not authenticated_user:
        users = get_allowed_users()
        hashed_password = users.get(identifier.lower())
        
        if hashed_password and verify_password(password, hashed_password):
            authenticated_user = identifier
        elif not users:
            raise HTTPException(
                status_code=401,
                detail="No users configured in the system. Please configure users in Supabase or set ALLOWED_USERS."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username/email or password",
            )
        
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
        samesite="lax"
    )
    
    return {"message": "Login successful", "user": authenticated_user}

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
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    # Check if user is known
    users = get_allowed_users()
    if users and username.lower() not in users:
        # If user signed in via Supabase Auth, verify client exists
        try:
            from app.supabase_client import get_supabase
            client = get_supabase()
            if not client:
                raise credentials_exception
        except Exception:
            raise credentials_exception
        
    return username
