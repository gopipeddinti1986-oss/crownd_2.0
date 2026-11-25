from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.database import Base, engine
from app.models import entities  # noqa: F401
from app.api.v1.routes import router

Base.metadata.create_all(bind=engine)
app=FastAPI(title=settings.app_name,version="1.0.0",description="CROWND creator commerce and performance marketing API")
origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type","X-Request-ID"])
app.include_router(router,prefix="/api/v1")
@app.get("/")
def root(): return {"name":"CROWND API","docs":"/docs","health":"/api/v1/health"}
