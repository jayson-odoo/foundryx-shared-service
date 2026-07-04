# Dreamz EMS — Backend (FastAPI)

FastAPI owns auth (bcrypt + JWT) and all domain data. The Next.js frontend's
NextAuth `CredentialsProvider` calls `POST /auth/login` and carries the returned
JWT in its session; protected calls send it as `Authorization: Bearer <jwt>`.

## Stack
FastAPI · SQLAlchemy · Pydantic v2 · python-jose (JWT) · bcrypt · Alembic (later).
Dev DB defaults to SQLite; switch to Postgres (`docker-compose.yml`) for prod parity.

## Run (dev)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.init_db          # create tables + seed demo user
uvicorn main:app --reload --port 8001
```
- API: http://localhost:8001  ·  OpenAPI docs: http://localhost:8001/docs
- Runs on **8001** (port 8000 is taken by sorento_crm backend locally).

## Demo credentials
`demo@example.com` / `demo1234`

## Endpoints
| Method | Path | Notes |
|--------|------|-------|
| POST | `/auth/login` | `{email,password}` → `{access_token, user}` |
| POST | `/auth/signup` | `{email,password,name?}` → user (auto-activated) |
| GET | `/auth/me` | Bearer token → current user |
| GET | `/health` | liveness |

## Layout
```
app/
  config.py        # pydantic-settings (.env)
  database.py      # engine, SessionLocal, Base, get_db
  security.py      # bcrypt hash/verify, JWT issue/decode
  dependencies.py  # get_current_user (Bearer)
  main.py          # FastAPI app + CORS + routers
  models/user.py   # User
  schemas/auth.py  # Login/Signup/UserOut
  api/v1/auth.py   # /auth/*
  api/v1/health.py # /health
scripts/init_db.py # create_all + seed
```

## Switch to Postgres
```bash
docker compose up -d
# set in .env:  DATABASE_URL=postgresql://dreamz:dreamz@localhost:5432/dreamz_ems
python -m scripts.init_db
```
