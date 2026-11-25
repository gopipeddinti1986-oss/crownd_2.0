import hashlib, hmac, secrets
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database import get_db
from app.models.entities import User

ALGORITHM = "HS256"
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180_000).hex()
    return f"{salt}${digest}"
def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180_000).hex(), digest)
    except ValueError: return False
def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, settings.jwt_secret, algorithm=ALGORITHM)
def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try: uid = int(jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])["sub"])
    except (JWTError, KeyError, ValueError): raise HTTPException(401, "Invalid or expired access token", headers={"WWW-Authenticate":"Bearer"})
    user = db.get(User, uid)
    if not user or not user.is_active: raise HTTPException(401, "Account is unavailable")
    return user
def require_role(*roles):
    def check(user: User = Depends(current_user)):
        if user.role not in roles: raise HTTPException(403, "You do not have permission for this action")
        return user
    return check
