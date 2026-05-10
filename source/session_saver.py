"""Writes a finished session (transcript + structured fields) to disk.

Files land in ``output/session_YYYYMMDD_HHMMSS.json``. The directory is created
on demand, so the user never has to set anything up by hand.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def save_session(
    transcript: str,
    structured: dict,
    output_dir: Path = Path("output"),
) -> Path:
    """Write the session to a timestamped JSON file. Returns the file path."""
    output_dir.mkdir(exist_ok=True)
    now = datetime.now()
    path = output_dir / f"session_{now.strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "timestamp": now.isoformat(timespec="seconds"),
        "transcript": transcript,
        "structured": structured,
    }
    # ensure_ascii=False so Serbian Cyrillic / Latin diacritics survive verbatim.
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Session saved to %s", path)
    return path
