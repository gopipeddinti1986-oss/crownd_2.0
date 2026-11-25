from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import secrets
from urllib.parse import urlsplit
from pwdlib import PasswordHash
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database import get_db
from app.models.entities import AuthSession, User

ALGORITHM="HS256"
oauth2=OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login",auto_error=False)
_password_hash=PasswordHash.recommended()
_dummy_hash=_password_hash.hash("CROWND-invalid-user-timing-only")

def hash_password(password: str) -> str:
    return _password_hash.hash(password)

def verify_and_update_password(password: str, stored: str) -> tuple[bool,str|None]:
    """Verify Argon2id and legacy PBKDF2 hashes; return a rehash when needed."""
    if stored.startswith("$argon2"):
        try:
            valid,updated=_password_hash.verify_and_update(password,stored)
            return valid,updated
        except (ValueError,TypeError):
            return False,None
    try:
        salt,digest=stored.split("$",1)
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180_000).hex()
        valid=hmac.compare_digest(actual,digest)
        return valid,hash_password(password) if valid else None
    except (ValueError,TypeError):
        return False,None

def verify_password(password: str, stored: str) -> bool:
    return verify_and_update_password(password,stored)[0]

def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def _refresh_mac(session_id: str,secret: str) -> str:
    message=f"{session_id}.{secret}".encode()
    return hmac.new(settings.jwt_secret.encode(),message,hashlib.sha256).hexdigest()

def create_refresh_secret(session_id: str|None=None) -> tuple[str,str,str]:
    session_id=session_id or secrets.token_urlsafe(18)
    secret=secrets.token_urlsafe(48)
    raw=f"{session_id}.{secret}.{_refresh_mac(session_id,secret)}"
    return session_id,raw,_digest(raw)

def verify_refresh_secret(raw: str) -> str|None:
    parts=raw.split(".")
    if len(parts)!=3: return None
    session_id,secret,provided=parts
    if not session_id or not secret or not hmac.compare_digest(_refresh_mac(session_id,secret),provided): return None
    return session_id

def create_access_token(user: User, session_id: str) -> str:
    now=datetime.now(timezone.utc)
    claims={"sub":str(user.id),"sid":session_id,"iat":now,"exp":now+timedelta(minutes=settings.access_token_minutes),"jti":secrets.token_urlsafe(12)}
    return jwt.encode(claims,settings.jwt_secret,algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        payload=jwt.decode(token,settings.jwt_secret,algorithms=[ALGORITHM],options={"require_exp":True,"require_sub":True})
        if not payload.get("sid"): raise JWTError("missing session")
        return payload
    except (JWTError,KeyError,ValueError,TypeError):
        raise HTTPException(status_code=401,detail="Authentication required",headers={"WWW-Authenticate":"Bearer"})

def current_user(request: Request, token: str|None=Depends(oauth2), db: Session=Depends(get_db)) -> User:
    if not token:
        raise HTTPException(status_code=401,detail="Authentication required",headers={"WWW-Authenticate":"Bearer"})
    payload=decode_access_token(token)
    try:
        user_id=int(payload["sub"])
        session_id=str(payload["sid"])
    except (KeyError,ValueError,TypeError):
        raise HTTPException(status_code=401,detail="Authentication required",headers={"WWW-Authenticate":"Bearer"})
    session=db.get(AuthSession,session_id)
    now=datetime.now(timezone.utc)
    if not session or session.user_id!=user_id or session.revoked_at is not None or _aware(session.expires_at)<=now:
        raise HTTPException(status_code=401,detail="Session expired or revoked",headers={"WWW-Authenticate":"Bearer"})
    user=db.get(User,user_id)
    if not user or not user.is_active or not user.email_verified:
        raise HTTPException(status_code=401,detail="Account is unavailable",headers={"WWW-Authenticate":"Bearer"})
    request.state.auth_session_id=session_id
    return user

def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def require_role(*roles: str):
    def check(user: User=Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403,detail="You do not have permission for this action")
        return user
    return check

def _trusted_proxy(peer: str) -> bool:
    try: peer_ip=ipaddress.ip_address(peer)
    except ValueError: return peer in {item.strip() for item in settings.trusted_proxy_ips.split(",") if item.strip()}
    for entry in settings.trusted_proxy_ips.split(","):
        entry=entry.strip()
        if not entry: continue
        try:
            if peer_ip in ipaddress.ip_network(entry,strict=False): return True
        except ValueError:
            if peer==entry: return True
    return False

def rate_limit_key(request: Request) -> str:
    """Use forwarded client IP only when its immediate peer is explicitly trusted."""
    peer=request.client.host if request.client else "unknown"
    forwarded=request.headers.get("x-forwarded-for","")
    address=forwarded.split(",",1)[0].strip() if _trusted_proxy(peer) and forwarded else peer
    return hmac.new(settings.jwt_secret.encode(),address.encode(),hashlib.sha256).hexdigest()

def require_trusted_origin(request: Request) -> None:
    origin=request.headers.get("origin")
    if not origin:
        if settings.is_production:
            raise HTTPException(status_code=403,detail="Request origin is required")
        return
    allowed={item.strip().rstrip("/") for item in settings.cors_origins.split(",") if item.strip()}
    allowed.add(settings.frontend_base_url.rstrip("/"))
    if origin.rstrip("/") in allowed:
        return
    peer=request.client.host if request.client else "unknown"
    forwarded_host=request.headers.get("x-forwarded-host","").split(",",1)[0].strip().lower()
    origin_host=(urlsplit(origin).netloc or "").lower()
    # Dynamic forwarded hosts are only tolerated in local dev previews. Production must
    # match the explicit HTTPS allowlist above, even when a request came through a proxy.
    if not settings.is_production and _trusted_proxy(peer) and forwarded_host and origin_host==forwarded_host:
        return
    raise HTTPException(status_code=403,detail="Request origin is not trusted")
