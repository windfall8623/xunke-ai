"""Server-only flags, model identity and optional read-only approved profile."""

import json
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.llm.configuration import resolve_llm_config
from app.rag.contracts import stable_hash, text_hash


def require_generation_types(question_types):
    settings = get_settings()
    if not settings.practice_enabled:
        raise AppError(503, "practice_disabled", "练习生成尚未开放")
    if "short_answer" in question_types:
        require_short_answer_grading()


def require_short_answer_grading():
    settings = get_settings()
    if not settings.practice_enabled or not settings.practice_short_answer_enabled:
        raise AppError(503, "short_answer_grading_unavailable", "简答题评分尚未开放")


def grading_model_configuration(settings=None):
    """Frozen system identity for evaluation; do not add production metadata."""
    settings = settings or get_settings()
    return _grading_model_configuration(resolve_llm_config(settings), settings)


def grading_model_configuration_from_config(config, settings=None):
    """Secret-free production identity shared by submission and runtime adapters."""
    settings = settings or get_settings()
    return {
        **_grading_model_configuration(config, settings),
        "config_source": config.source,
    }


def _grading_model_configuration(model, settings):
    return {
        "provider": model.provider,
        "model": model.model,
        "endpoint_hash": text_hash(model.base_url),
        "temperature": 0.2,
        "output_token_limit": settings.practice_grading_output_tokens,
        "model_context_window": settings.practice_grading_context_window,
        "max_retries": 0,
    }


def load_grading_profile(settings=None):
    """A missing, changed or invalid deployment artifact never grants authority.

    No HTTP input can select this path/hash, and this function never writes an
    approval. Applicability is checked separately against each frozen snapshot.
    """
    settings = settings or get_settings()
    if (
        not settings.practice_grading_profile_path
        or not settings.practice_grading_profile_hash
    ):
        return None
    try:
        path = Path(settings.practice_grading_profile_path)
        if path.stat().st_size > 65536:
            return None
        profile = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            return None
        expected = settings.practice_grading_profile_hash
        if (
            profile.get("profile_hash") != expected
            or stable_hash(
                {key: value for key, value in profile.items() if key != "profile_hash"}
            )
            != expected
        ):
            return None
        return profile
    except (OSError, ValueError, TypeError):
        return None
