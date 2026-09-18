"""Task-owned chat adapters; retrieval infrastructure never changes ownership.

Do not cache decrypted configs or SDK clients by user ID: a fresh resolution on
claim observes key rotation/deletion and every attempt closes its own transports.
Evaluation deliberately keeps its frozen, system-only provider/role policy.
"""

from contextlib import asynccontextmanager
from copy import copy

from app.core.config import get_settings
from app.core.errors import AppError
from app.rag.contracts import PipelineConfig, stable_hash, text_hash
from app.workers import providers

CHAT_JOB_KINDS = frozenset({
    "quiz", "report", "qa", "practice_generate", "practice_grade",
    "course_outline", "course_lesson", "course_tutor",
    "course_application_generate", "course_application_feedback",
})


async def resolve_task_llm_config(owner_id, settings=None):
    # Lazy import keeps injected workers independent of database configuration.
    from app.services.user_llm_config_service import resolve_actor_llm_config

    return await resolve_actor_llm_config(owner_id, settings=settings)


def _metadata(config, temperature=0.2):
    return {
        "provider": config.provider,
        "model": config.model,
        "endpoint_hash": text_hash(config.base_url),
        "temperature": temperature,
        "config_source": config.source,
    }


def _mark_source(adapter, config):
    # QA/practice constructors intentionally allowlist metadata. Attach only the
    # validated source enum, not the config object or arbitrary SDK attributes.
    adapter.model_configuration["config_source"] = config.source
    adapter.model_fingerprint = stable_hash(adapter.model_configuration)
    return adapter


@asynccontextmanager
async def isolated_dispatch(worker, job, actor):
    resolver = worker.runtime_resolver
    if job["mode"] != "production" or job["kind"] not in CHAT_JOB_KINDS:
        yield worker
        return
    if resolver is None:
        # Explicitly injected test engines have no production runtime. Real
        # build_runtime engines always carry the mandatory resolver marker.
        if getattr(worker.engine, "requires_actor_llm", False):
            raise RuntimeError("Production chat dispatch requires an actor LLM resolver")
        yield worker
        return
    settings = get_settings()
    config = await resolver(actor.owner_id, settings=settings)
    if not config.configured:
        raise AppError(409, "llm_configuration_required", "请先配置可用的大模型服务")
    clients = []
    try:
        isolated = copy(worker)
        isolated.engine = copy(worker.engine)
        # Legacy baseline contains a system generator and is evaluation-only.
        isolated.engine.legacy_baseline = None

        def model(**kwargs):
            value = providers.chat_model_from_config(config, **kwargs)
            clients.append(providers.ChatModelCloser(value))
            return value

        def meter(value, **kwargs):
            return providers.MeteredChat(
                value, config_source=config.source, api_key=config.api_key, **kwargs
            )

        chat = model(temperature=0.2, timeout_seconds=settings.provider_timeout_seconds)
        isolated.engine.generator = providers.LangChainQuizGenerator(meter(chat))
        isolated.report_generator = providers.ConfiguredReportGenerator(meter(chat))
        isolated.engine.qa_generator = _mark_source(providers.LangChainQaGenerator(
            meter(chat, purpose="qa_answer"),
            rewrite_llm=meter(chat, purpose="qa_rewrite"),
            semantic_llm=meter(chat, purpose="qa_validate"),
            model_configuration=_metadata(config),
        ), config)
        limits = PipelineConfig()
        practice_chat = chat.bind(max_tokens=limits.output_token_reserve)
        isolated.practice_provider = _mark_source(providers.LangChainPracticeProvider(
            meter(practice_chat, purpose="practice_generation", output_upper=limits.output_token_reserve),
            semantic_llm=meter(practice_chat, purpose="practice_validation", output_upper=limits.output_token_reserve),
            output_token_limit=limits.output_token_reserve,
            model_context_window=limits.model_context_window,
            model_configuration=_metadata(config),
        ), config)
        from app.practice.grading_config import grading_model_configuration_from_config

        isolated.grading_provider = providers.LangChainShortAnswerProvider(
            meter(chat.bind(max_tokens=settings.practice_grading_output_tokens),
                  purpose="practice_grading", output_upper=settings.practice_grading_output_tokens),
            output_token_limit=settings.practice_grading_output_tokens,
            model_context_window=settings.practice_grading_context_window,
            model_configuration=grading_model_configuration_from_config(config, settings),
        )
        isolated.course_generator = isolated.course_tutor_generator = None
        isolated.course_application_generator = None
        if settings.course_enabled:
            course_chat = model(temperature=0.3, max_tokens=4500,
                                timeout_seconds=settings.course_provider_timeout_seconds)
            reviewer = providers.TeachingReviewer(
                meter(course_chat.bind(max_tokens=1200, temperature=0),
                      purpose="course_teaching_review", output_upper=1200),
                model_configuration=_metadata(config, 0),
            )
            isolated.course_generator = providers.CourseGenerator(
                meter(course_chat.bind(max_tokens=3000), purpose="course_outline", output_upper=3000),
                meter(course_chat, purpose="course_lesson", output_upper=4500),
                timeout_seconds=settings.course_provider_timeout_seconds,
                model_configuration=_metadata(config, 0.3), reviewer=reviewer,
            )
            isolated.course_tutor_generator = providers.CourseTutorGenerator(
                meter(course_chat.bind(max_tokens=1500), purpose="course_tutor", output_upper=1500),
                timeout_seconds=settings.course_provider_timeout_seconds,
                model_configuration=_metadata(config, 0.3),
            )
            isolated.course_application_generator = providers.CourseApplicationGenerator(
                meter(course_chat.bind(max_tokens=4096),
                      purpose="course_application_generate", output_upper=4096),
                meter(course_chat.bind(max_tokens=1600, temperature=0),
                      purpose="course_application_feedback", output_upper=1600),
                timeout_seconds=settings.course_provider_timeout_seconds,
            )
        yield isolated
    finally:
        # Never call Runtime.close(): the store and retrieval clients are shared.
        # Close all task-owned transports even if one close fails. Do not mask a
        # provider/authorization failure (or cancellation) with SDK close errors.
        for client in reversed(clients):
            try:
                await client.aclose()
            except Exception:
                pass
