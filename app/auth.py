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
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-key-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

auth_router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a pbkdf2_hmac password hash (format: salt:hash)"""
    try:
        salt_hex, hash_hex = hashed_password.split(':')
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt, 100000)
        return secrets.compare_digest(key.hex(), hash_hex)
    except Exception:
        return False

def get_allowed_users():
    """
    Load allowed users from ALLOWED_USERS environment variable or users.json.
    Format of ALLOWED_USERS: username:hashed_password,username2:hashed_password2
    """
    users = {}
    
    # Check env var first (for Vercel)
    env_users = os.environ.get("ALLOWED_USERS")
    if env_users:
        try:
            for pair in env_users.split(","):
                if ":" in pair:
                    username, pwd = pair.split(":", 1)
                    users[username.strip()] = pwd.strip()
        except Exception:
            pass
            
    # Check local file if env var is empty or missing
    if not users:
        users_file = os.path.join(os.path.dirname(__file__), "..", "users.json")
        if os.path.exists(users_file):
            try:
                with open(users_file, "r") as f:
                    users = json.load(f)
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
    users = get_allowed_users()
    
    if not users:
        # If no users configured, block all logins or allow a default? Let's block.
        raise HTTPException(status_code=401, detail="No users configured in the system.")
        
    hashed_password = users.get(login_data.username)
    if not hashed_password or not verify_password(login_data.password, hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
        
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": login_data.username}, expires_delta=access_token_expires
    )
    
    # Set HTTP-only cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    
    return {"message": "Login successful", "user": login_data.username}

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
        
    # Verify user still exists in allowed list
    users = get_allowed_users()
    if username not in users:
        raise credentials_exception
        
    return username
