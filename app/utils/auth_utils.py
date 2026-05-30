from datetime import datetime, timedelta
from typing import Optional
import jwt
import bcrypt
from app.config import (
    JWT_SECRET_KEY, 
    JWT_ALGORITHM, 
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    BCRYPT_ROUNDS
)

def _truncate_password(password: str) -> bytes:
    """截断密码到 bcrypt 72 字节上限"""
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        return password_bytes[:72]
    return password_bytes

def hash_password(password: str) -> str:
    pwd_bytes = _truncate_password(password)
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = _truncate_password(plain_password)
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode('utf-8'))

def create_access_token(
    user_id: int,
    username: str,
    role: str,
    token_version: int = 1,
    expires_delta: Optional[timedelta] = None
) -> tuple[str, int]:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    expire_timestamp = int(expire.timestamp())
    
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "token_version": token_version,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    return token, JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except Exception:
        return None
