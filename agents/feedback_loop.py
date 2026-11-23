"""FrimeRise Views Retro-Feedback Engine (SQLite Analytics Loop)."""
from __future__ import annotations

from typing import Any, Dict, List

from database import get_job, get_top_performing_skills, record_feedback


def log_real_performance(
    job_id: str,
    platform: str,
    views: int,
    likes: int = 0,
    retention_pct: float = 0.0,
    hook_variant: str = "A",
) -> Dict[str, Any]:
    """Store real platform views/retention to continuously optimize future scripts & hooks."""
    job = get_job(job_id)
    skill_id = job["skill_id"] if job else "01_negative_hook"
    record_feedback(
        job_id=job_id,
        skill_id=skill_id,
        hook_variant=hook_variant,
        platform=platform,
        views=int(views),
        likes=int(likes),
        retention_pct=float(retention_pct),
    )
    return {
        "status": "recorded",
        "job_id": job_id,
        "skill_id": skill_id,
        "leaderboard": get_top_performing_skills(),
    }


def get_feedback_summary() -> List[Dict[str, Any]]:
    return get_top_performing_skills()
