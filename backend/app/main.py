import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.api.v1.routes import router
from app.api.v1.auth import limiter

logger=logging.getLogger("crownd.api")
app=FastAPI(title=settings.app_name,version="1.1.0",description="CROWND creator commerce and performance marketing API")
app.state.limiter=limiter
app.add_exception_handler(RateLimitExceeded,_rate_limit_exceeded_handler)
origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type","X-Request-ID"])

@app.middleware("http")
async def secure_response_headers(request: Request,call_next):
    response=await call_next(request)
    response.headers.setdefault("X-Content-Type-Options","nosniff")
    response.headers.setdefault("Referrer-Policy","no-referrer")
    response.headers.setdefault("X-Frame-Options","DENY")
    if request.url.path.startswith("/api/v1/auth/"):
        response.headers["Cache-Control"]="no-store"
        response.headers["Pragma"]="no-cache"
    return response

@app.exception_handler(Exception)
async def safe_unexpected_error(request: Request,exc: Exception):
    # Log only an exception class and static route path; never log request bodies, headers,
    # token query parameters, SQL values, or exception messages that might contain credentials.
    logger.error("Unhandled API error type=%s path=%s",type(exc).__name__,request.url.path)
    return JSONResponse(status_code=500,content={"detail":"An unexpected server error occurred"})

app.include_router(router,prefix="/api/v1")
@app.get("/")
def root(): return {"name":"CROWND API","docs":"/docs","health":"/api/v1/health"}
