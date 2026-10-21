from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .constants import CATEGORIES, ITEM_TYPES
from .database import init_db
from .routers import auth, claims, dashboard, items, matches
from .routers.matches import _scoring_info
from .services.embeddings import get_embedder

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_embedder()  # load models once at startup, not per request
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend for FindIt AI - Smart Lost & Found. Auth, item APIs, image storage, "
    "AI matching (CLIP + SentenceTransformer, or a simulated demo backend) on PostgreSQL + pgvector.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.storage_backend == "local":
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

api = APIRouter(prefix="/api/v1")
api.include_router(auth.router)
api.include_router(items.router)
api.include_router(matches.router)
api.include_router(claims.router)
api.include_router(dashboard.router)


@api.get("/meta", tags=["meta"])
def meta():
    """Static lookups for forms/filters plus how scores are produced (so the UI can label them honestly)."""
    return {
        "categories": [{"value": k, "label": v} for k, v in CATEGORIES.items()],
        "item_types": list(ITEM_TYPES),
        "scoring": _scoring_info(),
    }


app.include_router(api)


@app.get("/health", tags=["meta"])
def health():
    embedder = get_embedder()
    return {"status": "ok", "embedding_backend": embedder.name, "simulated_scores": embedder.is_simulated}
