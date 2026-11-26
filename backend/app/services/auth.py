from datetime import datetime, timedelta, timezone
import secrets
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.entities import AuthActionToken, AuthSession, User
from app.security import create_refresh_secret, _digest, hash_password

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def issue_action_token(db: Session,user: User,purpose: str,ttl: timedelta) -> str:
    now=utcnow()
    db.execute(update(AuthActionToken).where(AuthActionToken.user_id==user.id,AuthActionToken.purpose==purpose,AuthActionToken.consumed_at.is_(None)).values(consumed_at=now))
    raw=secrets.token_urlsafe(40)
    db.add(AuthActionToken(user_id=user.id,purpose=purpose,token_hash=_digest(raw),expires_at=now+ttl))
    return raw

def consume_action_token(db: Session,raw: str,purpose: str) -> tuple[AuthActionToken,User] | None:
    record=db.scalar(select(AuthActionToken).where(AuthActionToken.token_hash==_digest(raw),AuthActionToken.purpose==purpose).with_for_update())
    now=utcnow()
    if not record or record.consumed_at is not None or _aware(record.expires_at)<=now:
        return None
    user=db.get(User,record.user_id)
    if not user or not user.is_active:
        return None
    record.consumed_at=now
    return record,user

def create_session(db: Session,user: User) -> tuple[AuthSession,str]:
    session_id,raw,digest=create_refresh_secret()
    now=utcnow()
    session=AuthSession(id=session_id,user_id=user.id,refresh_token_hash=digest,expires_at=now+timedelta(days=settings.refresh_token_days),created_at=now,last_used_at=now)
    db.add(session)
    return session,raw

def revoke_sessions(db: Session,user_id: int,except_id: str|None=None) -> None:
    statement=update(AuthSession).where(AuthSession.user_id==user_id,AuthSession.revoked_at.is_(None))
    if except_id:
        statement=statement.where(AuthSession.id!=except_id)
    db.execute(statement.values(revoked_at=utcnow()))

def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
