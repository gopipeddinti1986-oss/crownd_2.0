from contextlib import asynccontextmanager
import logging
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.database import engine
from app.api.v1.routes import router
from app.api.v1.auth import limiter

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("crownd").setLevel(getattr(logging, settings.log_level.upper()))
logger = logging.getLogger("crownd.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.1.0",
    description="CROWND creator commerce and performance marketing API",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
origins = [origin.strip().rstrip("/") for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in settings.trusted_hosts.split(",") if host.strip()],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_security_and_access_log(request: Request, call_next):
    supplied_id = request.headers.get("x-request-id", "")
    request_id = supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_id) else uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.is_production:
        # API responses contain no executable documents; the static frontend's CSP is
        # configured separately in Nginx. TLS termination must add HSTS at the edge.
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; base-uri 'none'; frame-ancestors 'none'")
    if request.url.path.startswith("/api/v1/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    logger.info(
        "request completed request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(Exception)
async def safe_unexpected_error(request: Request, exc: Exception):
    # Do not log request bodies, headers, query strings, SQL parameters, or exception
    # messages that could contain credentials or customer information.
    request_id = getattr(request.state, "request_id", "unavailable")
    logger.error("Unhandled API error request_id=%s type=%s path=%s", request_id, type(exc).__name__, request.url.path)
    response = JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred"})
    if request_id != "unavailable":
        response.headers["X-Request-ID"] = request_id
    return response


app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {"name": "CROWND API", "health": "/api/v1/health/live"}
