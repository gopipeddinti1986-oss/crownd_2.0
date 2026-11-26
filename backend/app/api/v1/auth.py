from datetime import timedelta
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database import get_db
from app.models.entities import AuthActionToken, AuthSession, BrandProfile, CreatorProfile, User
from app.schemas.auth import LoginRequest, PasswordResetConfirm, PasswordResetRequest, RegisterRequest, TokenRequest
from app.security import _digest, _dummy_hash, create_access_token, current_user, create_refresh_secret, rate_limit_key, require_trusted_origin, verify_and_update_password, hash_password, verify_refresh_secret
from app.services.auth import consume_action_token, create_session, issue_action_token, revoke_sessions, utcnow, _aware
from app.services.notifications import create_notification, enqueue_action_email
from slowapi import Limiter

router=APIRouter(prefix="/auth",tags=["authentication"])
limiter=Limiter(key_func=rate_limit_key,storage_uri=settings.rate_limit_storage_uri,enabled=settings.rate_limit_enabled,headers_enabled=True)

def _user_payload(user: User) -> dict:
    return {"id":user.id,"name":user.name,"email":user.email,"role":user.role}

def _delivery_state() -> dict:
    if settings.email_mode=="disabled":
        return {"message":"Email verification is required. Email delivery is disabled; no message was sent. Configure SMTP and request a fresh link.","email_delivery_enabled":False}
    return {"message":"If this address is eligible, check for a verification message after background email processing. Provider acceptance does not guarantee inbox delivery.","email_delivery_enabled":True}

def _set_refresh_cookie(response: Response,raw: str) -> None:
    response.set_cookie(key="crownd_refresh",value=raw,max_age=settings.refresh_token_days*24*60*60,path="/api/v1/auth",secure=settings.use_secure_cookies,httponly=True,samesite=settings.cookie_samesite.lower(),domain=settings.cookie_domain or None)
    response.headers["Cache-Control"]="no-store"
    response.headers["Pragma"]="no-cache"

def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key="crownd_refresh",path="/api/v1/auth",secure=settings.use_secure_cookies,httponly=True,samesite=settings.cookie_samesite.lower(),domain=settings.cookie_domain or None)
    response.headers["Cache-Control"]="no-store"
    response.headers["Pragma"]="no-cache"

def _attempt_email(db: Session,user: User,purpose: str,token: str) -> None:
    # Queue inside the action-token transaction. The outbox encrypts the one-use link at rest;
    # the SMTP provider runs only in the separate worker process.
    enqueue_action_email(db,user,purpose,token,settings.frontend_base_url)

@router.post("/register",status_code=202)
@limiter.limit("10/minute")
def register(body: RegisterRequest,request: Request,response: Response,db: Session=Depends(get_db)):
    email=body.email.lower()
    user=db.scalar(select(User).where(User.email==email))
    if user is None:
        user=User(name=body.name,email=email,password_hash=hash_password(body.password),role=body.role,is_active=True,email_verified=False)
        db.add(user)
        try:
            db.flush()
            if body.role=="creator":
                username=(body.username or body.name.lower().replace(" ","_"))[:60]
                if db.scalar(select(CreatorProfile).where(CreatorProfile.username==username)):
                    username=f"{username[:52]}_{user.id}"
                db.add(CreatorProfile(user_id=user.id,username=username,niche=body.niche or "Lifestyle",platform=body.platform or "Instagram"))
            elif body.role=="brand":
                db.add(BrandProfile(user_id=user.id,name=body.brand_name or body.name,industry=body.industry or "Consumer",website=body.website or ""))
            token=issue_action_token(db,user,"verify_email",timedelta(hours=settings.verification_token_hours))
            _attempt_email(db,user,"verify_email",token)
            db.commit()
        except IntegrityError:
            db.rollback()
            return _delivery_state()
    return _delivery_state()

@router.post("/login")
@limiter.limit("8/minute")
def login(body: LoginRequest,request: Request,response: Response,db: Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==body.email.lower()))
    stored=user.password_hash if user else _dummy_hash
    valid,upgrade=verify_and_update_password(body.password,stored)
    if not user or not valid:
        raise HTTPException(status_code=401,detail="Email or password is incorrect",headers={"WWW-Authenticate":"Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403,detail="Account is unavailable")
    if not user.email_verified:
        raise HTTPException(status_code=403,detail={"code":"email_not_verified","message":"Verify your email before signing in."})
    if upgrade:
        user.password_hash=upgrade
    session,refresh=create_session(db,user)
    db.commit()
    _set_refresh_cookie(response,refresh)
    return {"access_token":create_access_token(user,session.id),"token_type":"bearer","expires_in":settings.access_token_minutes*60,"user":_user_payload(user)}

@router.post("/refresh")
@limiter.limit("20/minute")
def refresh(request: Request,response: Response,db: Session=Depends(get_db)):
    require_trusted_origin(request)
    raw=request.cookies.get("crownd_refresh")
    session_id=verify_refresh_secret(raw) if raw else None
    if not session_id:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401,detail="Refresh session is invalid")
    session=db.get(AuthSession,session_id,with_for_update=True)
    now=utcnow()
    if not session or session.revoked_at is not None or _aware(session.expires_at)<=now:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401,detail="Refresh session is invalid or expired")
    if not hmac.compare_digest(session.refresh_token_hash,_digest(raw)):
        session.revoked_at=now
        account=db.get(User,session.user_id)
        if account:
            notice="A refresh token was reused, so CROWND revoked that session. Sign in again and reset your password if you do not recognize this activity."
            create_notification(db,recipient_id=account.id,event_key=f"session-reuse:{session.id}",category="security",
                title="Session security alert",body=notice,action_path="/settings/notifications",
                email_subject="CROWND session security alert",email_body=notice,essential_email=True)
        db.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401,detail="Refresh token reuse detected; sign in again")
    user=db.get(User,session.user_id)
    if not user or not user.is_active or not user.email_verified:
        session.revoked_at=now
        db.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401,detail="Account is unavailable")
    _same_session_id,new_raw,new_digest=create_refresh_secret(session.id)
    session.refresh_token_hash=new_digest
    session.last_used_at=now
    db.commit()
    _set_refresh_cookie(response,new_raw)
    return {"access_token":create_access_token(user,session.id),"token_type":"bearer","expires_in":settings.access_token_minutes*60,"user":_user_payload(user)}

@router.post("/logout",status_code=204)
@limiter.limit("20/minute")
def logout(request: Request,response: Response,db: Session=Depends(get_db),user: User=Depends(current_user)):
    require_trusted_origin(request)
    session_id=getattr(request.state,"auth_session_id",None)
    session=db.get(AuthSession,session_id) if session_id else None
    if session and session.user_id==user.id and session.revoked_at is None:
        session.revoked_at=utcnow()
        db.commit()
    _clear_refresh_cookie(response)
    response.status_code=204
    return response

@router.post("/logout-all",status_code=204)
@limiter.limit("5/minute")
def logout_all(request: Request,response: Response,db: Session=Depends(get_db),user: User=Depends(current_user)):
    require_trusted_origin(request)
    revoke_sessions(db,user.id)
    db.commit()
    _clear_refresh_cookie(response)
    response.status_code=204
    return response

@router.get("/me")
def me(user: User=Depends(current_user),db: Session=Depends(get_db)):
    profile=None
    if user.role=="creator":
        row=db.scalar(select(CreatorProfile).where(CreatorProfile.user_id==user.id))
        if row:
            profile={"username":row.username,"niche":row.niche,"location":row.location,"bio":row.bio,"platform":row.platform,"followers":row.followers,"engagement":row.engagement,"availability":row.availability,"crown_score":row.crown_score,"trust_score":row.trust_score,"verification":row.verification}
    elif user.role=="brand":
        row=db.scalar(select(BrandProfile).where(BrandProfile.user_id==user.id))
        if row:
            profile={"name":row.name,"industry":row.industry,"website":row.website,"description":row.description,"verification":row.verification}
    return {**_user_payload(user),"email_verified":user.email_verified,"profile":profile}

@router.post("/email/verification/request",status_code=202)
@limiter.limit("5/hour")
def request_verification(body: PasswordResetRequest,request: Request,response: Response,db: Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==body.email.lower()))
    if user and user.is_active and not user.email_verified:
        token=issue_action_token(db,user,"verify_email",timedelta(hours=settings.verification_token_hours))
        _attempt_email(db,user,"verify_email",token)
        db.commit()
    return _delivery_state()

@router.post("/email/verification/confirm")
@limiter.limit("10/minute")
def confirm_verification(body: TokenRequest,request: Request,response: Response,db: Session=Depends(get_db)):
    result=consume_action_token(db,body.token,"verify_email")
    if not result:
        db.rollback()
        raise HTTPException(status_code=400,detail="Verification link is invalid, expired, or already used")
    _token,user=result
    user.email_verified=True
    db.execute(update(AuthActionToken).where(AuthActionToken.user_id==user.id,AuthActionToken.purpose=="verify_email",AuthActionToken.consumed_at.is_(None)).values(consumed_at=utcnow()))
    create_notification(db,recipient_id=user.id,event_key=f"email-verified:{_token.id}",category="account",
        title="Email verified",body="Your CROWND email address is verified. You can now sign in.",action_path="/settings/notifications")
    db.commit()
    return {"message":"Email verified. You can now sign in."}

@router.post("/password/reset/request",status_code=202)
@limiter.limit("5/hour")
def request_password_reset(body: PasswordResetRequest,request: Request,response: Response,db: Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==body.email.lower()))
    if user and user.is_active and user.email_verified:
        token=issue_action_token(db,user,"password_reset",timedelta(minutes=settings.password_reset_token_minutes))
        _attempt_email(db,user,"password_reset",token)
        db.commit()
    return {"message":"If an eligible account exists, CROWND can queue a message. Background processing and a configured email provider are required; delivery is not guaranteed.","email_delivery_enabled":settings.email_mode=="smtp"}

@router.post("/password/reset/confirm")
@limiter.limit("10/minute")
def confirm_password_reset(body: PasswordResetConfirm,request: Request,response: Response,db: Session=Depends(get_db)):
    result=consume_action_token(db,body.token,"password_reset")
    if not result:
        db.rollback()
        raise HTTPException(status_code=400,detail="Reset link is invalid, expired, or already used")
    _token,user=result
    user.password_hash=hash_password(body.new_password)
    revoke_sessions(db,user.id)
    create_notification(db,recipient_id=user.id,event_key=f"password-reset-completed:{_token.id}",category="security",
        title="Password changed",body="Your password was changed. If this was not you, reset it again and review your account sessions.",
        action_path="/settings/notifications",email_subject="Your CROWND password was changed",
        email_body="Your CROWND password was changed. If this was not you, reset it again and contact support.",essential_email=True)
    db.commit()
    return {"message":"Password updated. Please sign in again."}
