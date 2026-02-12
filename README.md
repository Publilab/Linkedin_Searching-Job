# SeekJob

Aplicación local para analizar CV, generar estrategia con IA y buscar ofertas en portales permitidos.

## Stack

- Backend: FastAPI + SQLAlchemy + SQLite + scheduler interno.
- Frontend: Next.js.
- Desktop: Tauri (macOS Intel/Monterey) con backend embebido.
- LLM: OpenAI o Google Gemini (fallback determinístico si falla o no hay key).

## Flujo principal

1. Subes CV (`.pdf` o `.docx`).
2. Se extrae texto y se crea resumen editable.
3. IA genera análisis del perfil y consultas sugeridas.
4. Ejecutas búsqueda en fuentes habilitadas.
5. Se calcula score (`match`, `llm_fit`, `final_score`) y se guarda en SQLite.
6. Opcional: activas segundo plano (cada 60 min, solo con la app abierta).

## Variables `.env` (modo web/dev)

Archivo raíz `.env.example`:

- `DATABASE_URL=sqlite:///./app.db`
- `SCHEDULER_INTERVAL_MINUTES=60`
- `LLM_ENABLED=true`
- `LLM_PROVIDER=openai`
- `LLM_MODEL=gpt-5-mini`
- `OPENAI_API_KEY=...`
- `OPENAI_BASE_URL=`
- `GEMINI_API_KEY=`
- `LLM_TIMEOUT_SECONDS=90`
- `LLM_MAX_RETRIES=3`
- `LLM_MAX_JOBS_PER_RUN=25`
- `LLM_PROMPT_VERSION=v1`

En desktop no necesitas editar `.env` para la API key: se configura desde la UI.

## Ejecutar en modo web (actual)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000/api npm run dev
```

## Ejecutar en modo desktop (Tauri)

### Prerrequisitos macOS

- Xcode Command Line Tools.
- Rust (`rustup`, `cargo`).
- Node/npm.
- Python 3.

Instalacion rapida de Rust:

```bash
curl https://sh.rustup.rs -sSf | sh
source "$HOME/.cargo/env"
```

### Desarrollo desktop

```bash
./scripts/dev_seekjob_desktop.sh
```

Esto abre la ventana nativa de SeekJob y lanza backend local embebido.

### Build de `SeekJob.app`

```bash
./scripts/build_seekjob_desktop_macos.sh
```

Bundle esperado:

`desktop/src-tauri/target/release/bundle/macos/SeekJob.app`

Nota: el primer inicio puede demorar (hasta ~1 minuto) porque el backend embebido se extrae e inicializa.

Si ejecutas `npm run tauri:build` directamente y falta `cargo`, ahora veras un mensaje guiado para instalar Rust.

## Desktop: decisiones implementadas

- UI dentro de app nativa (sin usar navegador para la interfaz).
- Backend embebido en el bundle (`seekjob-backend` via PyInstaller).
- Links de ofertas se abren forzando Chrome (`open -a "Google Chrome"`), con fallback al navegador por defecto.
- Persistencia en:
  - `~/Library/Application Support/SeekJob/app.db`
  - `~/Library/Application Support/SeekJob/logs/`
- Migración inicial automática desde `backend/app.db` (si existe) en primer inicio.
- Scheduler solo corre con la app abierta.
- Configuración LLM desde UI (provider/model/key/enable/test) con key en keychain o fallback protegido.

## Portales y dedupe

- Activos permitidos: `linkedin_public`, `bne_public`, `empleos_publicos_public`.
- Dedupe:
  1. `source + external_job_id`
  2. fallback por `canonical_url_hash`
- Si la oferta existe: actualiza datos (incluyendo `applicant_count`) sin duplicar filas.

## Endpoints principales

- `POST /api/cv/upload`
- `GET /api/cv/{cv_id}/summary`
- `PUT /api/cv/{cv_id}/summary`
- `POST /api/cv/{cv_id}/analyze`
- `GET /api/cv/{cv_id}/strategy`
- `GET /api/session/current`
- `GET /api/session/history`
- `POST /api/session/state`
- `POST /api/session/resume`
- `POST /api/session/close`
- `POST /api/session/purge-db`
- `POST /api/searches`
- `PATCH /api/searches/{search_id}`
- `POST /api/searches/{search_id}/run`
- `GET /api/searches/{search_id}/results`
- `DELETE /api/searches/{search_id}/results`
- `GET /api/searches/{search_id}/facets`
- `GET /api/searches/{search_id}/new-count`
- `GET /api/searches/sources`
- `PATCH /api/searches/results/{result_id}/check`
- `POST /api/interactions`
- `GET /api/insights/cv/{cv_id}/latest`
- `POST /api/insights/cv/{cv_id}/generate`
- `GET /api/settings/llm`
- `PUT /api/settings/llm`
- `POST /api/settings/llm/test`
- `POST /api/scheduler/start`
- `POST /api/scheduler/stop`
- `GET /api/scheduler/status`

## Notas de scoring

- Con LLM: `0.55*llm_fit + 0.25*deterministico + 0.10*recencia + 0.10*ubicacion`.
- Fallback: `0.75*deterministico + 0.15*recencia + 0.10*ubicacion`.
- Regla de producto: ofertas con `applicant_count >= 100` se excluyen.
