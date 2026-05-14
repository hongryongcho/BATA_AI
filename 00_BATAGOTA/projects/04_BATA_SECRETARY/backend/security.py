"""
JWT 토큰 생성 및 검증 모듈.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import hmac
import hashlib
import base64
from dotenv import load_dotenv

load_dotenv()

# .env 파일에서 시크릿 키와 토큰 만료 시간 가져오기
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "a07f22d1118862e6554c964dbb752e9d34aa5dbb0efc7a684d689a8f68ac6b1a")
TOKEN_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "8"))


def _base64_url_encode(data: bytes) -> str:
    """Base64 URL 인코딩 (패딩 제거)."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _base64_url_decode(data: str) -> bytes:
    """Base64 URL 디코딩 (패딩 추가)."""
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def create_token(user_id: str, username: str, role: str = "counselor") -> str:
    """
    JWT 토큰 생성.
    
    Args:
        user_id: 사용자 고유 ID
        username: 사용자명
        role: 역할 ('counselor', 'approver', 'admin')
    
    Returns:
        JWT 토큰 문자열
    """
    # Header
    header = {
        "alg": "HS256",
        "typ": "JWT",
    }
    
    # Payload
    now = datetime.utcnow()
    expiry = now + timedelta(hours=TOKEN_EXPIRY_HOURS)
    
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
    }
    
    # Encoding
    header_encoded = _base64_url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_encoded = _base64_url_encode(json.dumps(payload, separators=(",", ":")).encode())
    
    # Signature
    message = f"{header_encoded}.{payload_encoded}".encode()
    signature = hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest()
    signature_encoded = _base64_url_encode(signature)
    
    return f"{header_encoded}.{payload_encoded}.{signature_encoded}"


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    JWT 토큰 검증 및 페이로드 추출.
    
    Args:
        token: JWT 토큰 문자열
    
    Returns:
        토큰이 유효하면 페이로드 dict, 유효하지 않으면 None
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        
        header_encoded, payload_encoded, signature_encoded = parts
        
        # Signature 검증
        message = f"{header_encoded}.{payload_encoded}".encode()
        expected_signature = hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest()
        expected_signature_encoded = _base64_url_encode(expected_signature)
        
        if not hmac.compare_digest(signature_encoded, expected_signature_encoded):
            return None
        
        # Payload 디코딩
        payload_json = _base64_url_decode(payload_encoded).decode()
        payload = json.loads(payload_json)
        
        # 만료 시간 검증
        exp = payload.get("exp")
        if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
            return None
        
        return payload
    
    except Exception as e:
        print(f"[WARN] Token verification failed: {e}")
        return None


def extract_token_from_header(auth_header: Optional[str]) -> Optional[str]:
    """
    Authorization 헤더에서 토큰 추출.
    
    Args:
        auth_header: "Bearer <token>" 형식의 헤더
    
    Returns:
        토큰 문자열 또는 None
    """
    if not auth_header:
        return None
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    
    return parts[1]
