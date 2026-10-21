# FindIt AI — Backend

FastAPI + PostgreSQL/pgvector backend for the FindIt AI lost-and-found app: accounts, item reports with photos, AI matching, claim requests and a dashboard.

```
React Frontend ──► FastAPI (/api/v1)
                    ├─ auth (JWT) · items · matches · claims · dashboard
                    ├─ image storage (local disk or S3, EXIF stripped)
                    └─ matching service (CLIP image + SentenceTransformer text, weighted cosine)
                          ▼
                   PostgreSQL + pgvector: users · items · item_embeddings · matches (+ claims)
```

## Run it

**Docker (recommended):**

```bash
docker compose up --build        # API on http://localhost:8000, docs on /docs
```

This starts Postgres with pgvector, seeds demo data, and serves the API.

**Local:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # point DATABASE_URL at a Postgres with the pgvector extension available
python -m app.seed               # optional demo data
uvicorn app.main:app --reload
```

**Database connection:** `.env` already points at the Postgres in `docker-compose.yml` (`postgresql+psycopg://findit:findit@localhost:5432/findit`). To run only the database and the API locally:

```bash
docker compose up -d db          # Postgres 16 + pgvector
python -m app.db_check           # verifies connection + pgvector, creates tables/indexes, prints row counts
python -m app.seed               # demo data
uvicorn app.main:app --reload
```

Hosted Postgres (Neon, Supabase, RDS) works too: enable the `vector` extension and set `DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/DB` (add `?sslmode=require` if the provider needs it).

Demo login (seeded): `demo@findit.demo` / `demo12345`. Interactive API docs: `http://localhost:8000/docs`.

**Tests:** `pip install -r requirements-dev.txt && pytest` (runs on SQLite, no Postgres needed).

## Matching

```
overall = 60% image similarity + 40% description similarity      (IMAGE_WEIGHT / TEXT_WEIGHT)
```

1. **Hard filters:** opposite type (lost↔found), open status, different owner, date window (±30 days, found can't predate lost), same category (or "other"), and geographic radius when both reports have coordinates.
2. **Scoring:** cosine similarity of image vectors (512-d) and text vectors (384-d), rescaled by a per-modality floor to 0–100. A report without a photo falls back to description-only.
3. **Compatibility signals** returned beside the score: location (`Same spot` / `Same area` / `Nearby` / `Different area`), days apart, and a plain-language `explanation`.
4. Matching runs in a background task after the upload response, so `POST /items` returns immediately. If `GET /items/{id}/matches` is called first it returns `indexing: true`; retry after a second.

### Simulated vs real scores

| `EMBEDDING_BACKEND` | Text | Images | Notes |
|---|---|---|---|
| `demo` (default) | hashed keyword/bigram vectors with a small synonym list | centre-weighted colour histograms | **Not CLIP or SentenceTransformer.** Scores are simulated; the API says so (`scoring.is_simulated: true`). No model downloads. |
| `real` | `all-MiniLM-L6-v2` (384-d) | `clip-ViT-B-32` (512-d) | `pip install -r requirements-ml.txt`. Retune `IMAGE_SIM_FLOOR` (CLIP image–image cosine rarely falls below ~0.5). |

Each stored embedding records its backend, and only vectors from the same backend are ever compared, so switching backends won't mix incompatible vector spaces (re-upload or re-index old items after switching).

## API (`/api/v1`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register`, `/auth/login` | – | JSON body → `{access_token, user}` (send as `Authorization: Bearer …`) |
| GET | `/auth/me` | ✔ | Current user |
| GET | `/meta` | – | Categories, item types, scoring formula + `is_simulated` |
| POST | `/items` | ✔ | **multipart/form-data**: `type, title, category, description, location_text, date_event` + optional `lat, lng, distinguishing_features, private_detail, image` |
| GET | `/items` | – | Filters: `q, type, category, location, date_from, date_to, status, limit, offset` → `{items,total,…}` |
| GET | `/items/mine` | ✔ | My reports |
| GET / PATCH / DELETE | `/items/{id}` | – / ✔ owner / ✔ owner | Details, edit (title, description, features, status), delete |
| GET | `/items/{id}/matches` | – | Ranked matches with `image_score, text_score, final_score, location_label, days_apart, explanation, other_item`. `?refresh=true` (owner), `?min_score=`, `?limit=` |
| GET | `/matches/mine` | ✔ | Matches across my reports |
| POST | `/matches/{id}/dismiss` | ✔ | Hide a suggestion |
| POST | `/claims` | ✔ | `{item_id, lost_item_id?, message, verification_detail?}` → pending claim |
| GET | `/claims/mine`, `/claims/received` | ✔ | Claims I made / claims on my reports |
| PATCH | `/claims/{id}` | ✔ | `{status}`: owner → `approved`/`rejected`; claimant → `withdrawn` |
| GET | `/dashboard` | ✔ | Global stats, my stats, my reports, recent activity |
| GET | `/health` | – | Liveness + active embedding backend |

Uploaded images are served from `/uploads/…` (local storage) and `image_url` values are absolute.

### Frontend integration (service layer)

```js
const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });

export const login = (email, password) =>
  fetch(`${API}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }) }).then(r => r.json());

export const reportItem = (formData) =>           // FormData with the fields above (+ image file)
  fetch(`${API}/items`, { method: "POST", headers: auth(), body: formData }).then(r => r.json());

export const searchItems = (params) =>
  fetch(`${API}/items?${new URLSearchParams(params)}`).then(r => r.json());

export const getMatches = (itemId) =>
  fetch(`${API}/items/${itemId}/matches`, { headers: auth() }).then(r => r.json());

export const claimItem = (body) =>
  fetch(`${API}/claims`, { method: "POST", headers: { ...auth(), "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then(r => r.json());
```

Errors come back as `{"detail": "..."}` with friendly messages (422 validation, 401 sign-in needed, 409 duplicate claim).

## Privacy & safety choices

- Owner emails and contact details are never returned by any item, match or claim endpoint; claimants appear by first name only.
- `private_detail` (serial number, contents…) is visible only to the report's owner. Claimants supply a `verification_detail`, and the owner compares the two before approving.
- Uploaded photos are re-encoded to JPEG, which strips EXIF data such as GPS coordinates.
- Claims are **requests reviewed by the report owner, not proof of identity.** There is no in-app contact handover yet; for a real deployment, hand off through a campus lost-and-found desk or add moderated messaging.

## What is and isn't done

- Demo embedder, matching math, claims, dashboard, auth and storage are implemented; the routers are covered by `tests/test_api.py`.
- Tables are created at startup (`init_db`) — switch to Alembic migrations before a real deployment.
- Not included: email/push notifications, rate limiting, password reset, admin moderation, and background-job infrastructure beyond FastAPI `BackgroundTasks` (swap to Celery/RQ for heavy `real` models).

## Layout

```
app/
  main.py · config.py · database.py · models.py · schemas.py · serializers.py · security.py · deps.py · seed.py
  routers/   auth · items · matches · claims · dashboard
  services/  embeddings (demo + CLIP/SentenceTransformer) · matching · storage
tests/       conftest.py · test_api.py
```
