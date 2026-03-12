from __future__ import annotations

import os

import uvicorn
from app.main import app as fastapi_app


def main() -> None:
    port = int(os.getenv("SEEKJOB_PORT") or os.getenv("PORT") or "8000")
    host = os.getenv("SEEKJOB_HOST") or "127.0.0.1"
    log_level = os.getenv("SEEKJOB_LOG_LEVEL") or "info"

    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        reload=False,
        workers=1,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
