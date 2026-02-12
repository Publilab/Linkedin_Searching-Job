from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from app.config import settings


def prepare_desktop_runtime() -> None:
    data_dir = _data_dir()
    if data_dir is None:
        return

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)

    marker = data_dir / "migration.marker"
    target_db = data_dir / "app.db"

    if marker.exists():
        return

    copied_from = None
    if not target_db.exists():
        for candidate in _legacy_db_candidates():
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                shutil.copy2(candidate, target_db)
                copied_from = str(candidate)
                break
            except OSError:
                continue

    marker_payload = {
        "created_at": datetime.utcnow().isoformat(),
        "copied_from": copied_from,
        "target": str(target_db),
    }
    marker.write_text(_to_json(marker_payload))


def _data_dir() -> Path | None:
    raw = (settings.seekjob_data_dir or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _legacy_db_candidates() -> list[Path]:
    out: list[Path] = []

    configured = (settings.seekjob_legacy_db_path or "").strip()
    if configured:
        out.append(Path(configured).expanduser())

    # repo-local default when running from source checkout
    backend_dir = Path(__file__).resolve().parents[2]
    out.append(backend_dir / "app.db")

    # explicit legacy path requested for first migration fallback
    out.append(Path("/Volumes/PubliLab-EXHD/Publilab/Projects/PubliLab/GitHub/Linkedin/backend/app.db"))
    out.append(Path("/Volumes/PubliLab-EXHD/Publilab/Projects/PubliLab/GitHub/linkedin/backend/app.db"))

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in out:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _to_json(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True, indent=2)
