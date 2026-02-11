# LinkedIn CV Job Finder (Greenfield + LLM)

Aplicacion local para:

1. Subir CV en PDF/DOCX.
2. Revisar/confirmar resumen estructurado.
3. Analizar perfil con LLM externo (OpenAI GPT-5-mini por defecto, con fallback deterministico).
4. Buscar ofertas en portales permitidos sin login (`LinkedIn public`, `BNE public` y `Empleos Públicos`).
5. Calcular score hibrido por fit deterministico + fit LLM + recencia + ubicacion.
6. Guardar resultados en SQLite con checklist y enlace de postulacion.
7. Re-buscar en segundo plano solo cuando se activa manualmente (default 60 minutos) y mostrar nuevas arriba.

## Estructura

- `backend/`: FastAPI + SQLAlchemy + scheduler interno + capa LLM.
- `frontend/`: Next.js UI bilingue ES/EN.

## Reglas de dedupe

1. Primero por `source + external_job_id`.
2. Si no hay id, fallback por `canonical_url_hash`.
3. Si la oferta ya existe, se actualizan sus datos (incluye `applicant_count`) sin duplicar filas.

## Modelo de datos (SQLite)

- `cv_documents`
- `candidate_profiles`
- `search_configs`
- `job_postings`
- `search_results`
- `scheduler_runs`
- `scheduler_state`
- `result_checks`

## LLM y privacidad

- Proveedor configurable por `LLM_PROVIDER` (`openai` o `google_gemini`).
- Default recomendado: `openai` + `LLM_MODEL=gpt-5-mini`.
- Modo: hibrido con fallback deterministico.
- Redaccion PII previa al envio (email, telefono, URL y nombre probable).
- Si faltan credenciales del proveedor activo, la app no se rompe y funciona en fallback.

## Variables de entorno

Usa `.env.example` como base:

- `DATABASE_URL`
- `SCHEDULER_INTERVAL_MINUTES`
- `LLM_ENABLED`
- `LLM_PROVIDER`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `GEMINI_API_KEY`
- `LLM_MODEL`
- `LLM_TIMEOUT_SECONDS`
- `LLM_MAX_RETRIES`
- `LLM_MAX_JOBS_PER_RUN`
- `LLM_PROMPT_VERSION`

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000/api npm run dev
```

## Endpoints principales

- `POST /api/cv/upload`
- `GET /api/cv/{cv_id}/summary`
- `PUT /api/cv/{cv_id}/summary`
- `POST /api/cv/{cv_id}/analyze`
- `GET /api/cv/{cv_id}/strategy`
- `GET /api/session/current`
- `POST /api/session/state`
- `POST /api/session/resume`
- `POST /api/session/close`
- `POST /api/searches`
- `GET /api/searches/sources`
- `POST /api/searches/{search_id}/run`
- `GET /api/searches/{search_id}/results`
- `GET /api/searches/{search_id}/facets`
- `GET /api/searches/{search_id}/new-count`
- `PATCH /api/searches/results/{result_id}/check`
- `POST /api/scheduler/start`
- `POST /api/scheduler/stop`
- `GET /api/scheduler/status`

## Notas de scoring

- Con LLM: `0.55*llm_fit + 0.25*deterministico + 0.10*recencia + 0.10*ubicacion`.
- Fallback: `0.75*deterministico + 0.15*recencia + 0.10*ubicacion`.

## Mejora de estrategia

- El parser de CV identifica secciones completas (experiencia, educación/formación, habilidades e idiomas) en ES/EN.
- Se prioriza experiencia + educación para construir consultas de búsqueda.
- `GET /api/cv/{cv_id}/strategy` entrega queries recomendadas y roles demandados (internet/fallback).

## Ventanas de publicación soportadas

- `1h`, `3h`, `8h`, `24h`, `72h`, `168h (1 semana)`, `720h (1 mes)`.

## Paginación de resultados

- `GET /api/searches/{search_id}/results` soporta `page` (default `1`) y `page_size` (default `50`, max `200`).

## Multi-portal permitido

- Selector de portales en UI (`Búsqueda`) para elegir fuentes por corrida.
- Columna `Fuente` en la tabla de resultados.
- Filtros/facetas incluyen `source`.
- Estado actual de conectores:
  - Activos: `linkedin_public`, `bne_public`, `empleos_publicos_public`.
  - Mostrados pero no activos: `trabajando_public`, `indeed_public` (requieren integración oficial/API).
