import json
import os
from datetime import datetime, timezone

_LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "audit.jsonl")


def _read_all_entries() -> list:
    if not os.path.exists(_LOG_FILE):
        return []
    with open(_LOG_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_entry(entry: dict) -> None:
    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_submission(
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_score: float,
    heuristic_score: float,
    status: str = "not_appealed",
) -> None:
    _append_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "heuristic_score": heuristic_score,
        "status": status,
    })


def log_appeal(
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_score: float,
    heuristic_score: float,
    reasoning: str,
) -> None:
    """Appends an appeal entry. Presence of 'reasoning' distinguishes appeals from submissions."""
    _append_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "heuristic_score": heuristic_score,
        "status": "under_review",
        "reasoning": reasoning,
    })


def get_submission(content_id: str) -> dict | None:
    """Returns the original submission entry for a content_id, or None if not found."""
    for entry in _read_all_entries():
        if entry.get("content_id") == content_id and "reasoning" not in entry:
            return entry
    return None


def appeal_exists(content_id: str, creator_id: str) -> bool:
    """Returns True if this creator has already filed an appeal for this content."""
    for entry in _read_all_entries():
        if (
            entry.get("content_id") == content_id
            and entry.get("creator_id") == creator_id
            and "reasoning" in entry
        ):
            return True
    return False


def read_recent_logs(limit: int = 100) -> list:
    entries = _read_all_entries()
    return list(reversed(entries[-limit:]))
