"""Explicit, metered external providers for the owner process.

Missing configuration stays a visible provider failure. No mock answers, default
OpenAI discovery, SDK retries, or request-time global settings are introduced.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings
from app.llm.configuration import resolve_llm_config
from app.llm.langchain_factory import ChatModelCloser, create_chat_model, chat_model_from_config
from app.llm.responses import response_text
from app.models.learning import ReportText
from app.practice.providers import LangChainPracticeProvider
from app.practice.grade_provider import LangChainShortAnswerProvider
from app.practice.grading_config import grading_model_configuration
from app.prompts.report_prompt import REPORT_HUMAN_PROMPT, REPORT_SYSTEM_PROMPT
from app.qa.generator import LangChainQaGenerator
from app.rag.artifact_store import OwnerIndexStore
from app.rag.budget import count_tokens
from app.rag.contracts import PipelineConfig, RerankerConfig, text_hash
from app.rag.engine import RagEngine
from app.rag.errors import GenerationValidationFailed, RetrievalUnavailable
from app.rag.providers.embedding_adapter import DashScopeEmbedding
from app.rag.providers.generator import LangChainQuizGenerator
from app.rag.providers.llm_reranker import LLMReranker
from app.rag.providers.llm_reranker_config import llm_reranker_config
from app.rag.providers.reranker import RemoteReranker
from app.rag.providers.web_evidence import (
    SafeWebFetcher,
    TavilySearchClient,
    WebEvidenceProvider,
)
from app.services.provider_meter import MeteredChat, MeteredHTTP, call_external
from app.services.source_service import reauthorize_scope
from app.teaching.generator import CourseGenerator
from app.teaching.tutor import CourseTutorGenerator
from app.teaching.reviewer import TeachingReviewer
from app.teaching.application import CourseApplicationGenerator


class UnconfiguredEmbedding:
    def __init__(self, model, dimensions):
        self.model, self.dimensions = model, dimensions

    async def embed_documents(self, texts, *, budget=None):
        raise RetrievalUnavailable("Embedding provider is not configured")

    async def embed_query(self, text, *, budget=None):
        raise RetrievalUnavailable("Embedding provider is not configured")


class MeteredStageHTTP:
    def __init__(self, stage, timeout_seconds):
        self.stage, self.timeout_seconds = stage, timeout_seconds

    async def post(self, url, **kwargs):
        async def send():
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, follow_redirects=False, trust_env=False
            ) as client:
                return await client.post(url, **kwargs)

        data = kwargs.get("json", {})
        return await call_external(
            self.stage,
            send,
            input_upper=count_tokens(json.dumps(data, ensure_ascii=False)),
        )


class MeteredFetchClient:
    """Journal every redirect request, after SafeWebFetcher pins a public IP."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            follow_redirects=False, timeout=15, trust_env=False
        )

    @asynccontextmanager
    async def stream(self, *args, **kwargs):
        manager = self.client.stream(*args, **kwargs)

        async def enter():
            # Returning a wrapper avoids pretending an unread streaming body has
            # model token usage. Fetch has an explicit zero provider-price entry.
            return {"response": await manager.__aenter__()}

        opened = await call_external("fetch", enter)
        try:
            yield opened["response"]
        finally:
            await manager.__aexit__(None, None, None)

    async def aclose(self):
        await self.client.aclose()


class ConfiguredReportGenerator:
    def __init__(self, llm):
        self.llm = llm

    async def __call__(self, *, topic, questions, answer_records, score_summary):
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = REPORT_HUMAN_PROMPT.format(
            topic=topic,
            quiz_json=json.dumps(questions, ensure_ascii=False),
            answer_records=json.dumps(answer_records, ensure_ascii=False),
            score_summary=json.dumps(score_summary, ensure_ascii=False),
        )
        response = await self.llm.ainvoke(
            [SystemMessage(content=REPORT_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        try:
            raw = response_text(response).strip()
        except ValueError as exc:
            raise GenerationValidationFailed(
                "Report provider returned no complete text"
            ) from exc
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        try:
            payload = json.loads(fenced[1] if fenced else raw)
            required = {
                "mastered_points",
                "weak_points",
                "three_line_summary",
                "advice",
                "share_quote",
            }
            if not isinstance(payload, dict) or not required <= set(payload):
                raise ValueError("Incomplete report")
            report = ReportText.model_validate(payload)
            if (
                len(report.three_line_summary) != 3
                or not all(line.strip() for line in report.three_line_summary)
                or not report.advice
                or not report.share_quote.strip()
            ):
                raise ValueError("Incomplete report text")
            return report
        except (ValueError, TypeError) as exc:
            raise GenerationValidationFailed("Report text failed validation") from exc


@dataclass
class Runtime:
    engine: RagEngine
    report_generator: ConfiguredReportGenerator | None
    clients: list = field(default_factory=list)
    practice_provider: LangChainPracticeProvider | None = None
    grading_provider: LangChainShortAnswerProvider | None = None
    course_generator: CourseGenerator | None = None
    course_tutor_generator: CourseTutorGenerator | None = None
    course_application_generator: CourseApplicationGenerator | None = None

    async def close(self):
        try:
            for client in self.clients:
                await client.aclose()
        finally:
            if hasattr(self.engine.store, "aclose"):
                await self.engine.store.aclose()
            else:
                self.engine.store.close()


def build_runtime(settings=None, *, role="owner") -> Runtime:
    settings = settings or get_settings()
    if settings.vector_backend == "qdrant":
        from app.rag.remote_index_store import RemoteIndexStore

        store = RemoteIndexStore(settings.data_dir, settings=settings, writable=role != "generation")
    else:
        if role == "generation":
            raise ValueError("Generation replicas require Qdrant")
        store = OwnerIndexStore(settings.data_dir, process_role="rag_owner")
        store.registry_enabled = settings.vector_projection_registry_required
        store.backend = "chroma"
        store.target_revision = settings.vector_target_revision
    clients = []
    try:
        embedding = (
            DashScopeEmbedding(
                api_key=settings.dashscope_api_key,
                model=settings.dashscope_embedding_model,
                dimensions=settings.embedding_dimensions,
                base_url=settings.dashscope_base_url,
                client=MeteredHTTP(),
                timeout_seconds=min(settings.provider_timeout_seconds, 60),
            )
            if settings.dashscope_api_key
            else UnconfiguredEmbedding(
                settings.dashscope_embedding_model, settings.embedding_dimensions
            )
        )
        if settings.query_embedding_cache_enabled:
            from redis.asyncio import Redis
            from redis.backoff import NoBackoff
            from redis.asyncio.retry import Retry
            from app.rag.providers.query_embedding_cache import (
                EmbeddingSignature, QueryCachedEmbedding,
            )

            cache_client = Redis(
                host=settings.redis_cache_host,
                port=settings.redis_cache_port,
                db=settings.redis_cache_db,
                password=settings.redis_cache_password,
                ssl=settings.redis_cache_tls,
                socket_connect_timeout=settings.redis_connect_timeout_ms / 1000,
                socket_timeout=settings.redis_command_timeout_ms / 1000,
                max_connections=settings.redis_max_connections,
                retry=Retry(NoBackoff(), 0),
                retry_on_timeout=False,
                decode_responses=False,
            )
            embedding = QueryCachedEmbedding(
                embedding,
                client=cache_client,
                signature=EmbeddingSignature(
                    provider="openai-compatible-embedding",
                    base_url=settings.dashscope_base_url,
                    model=settings.dashscope_embedding_model,
                    model_revision=settings.embedding_model_revision,
                    dimensions=settings.embedding_dimensions,
                    request_params={"encoding_format": "float"},
                ),
                hmac_secret=settings.redis_cache_password,
                ttl_seconds=settings.query_embedding_cache_ttl_seconds,
                operation_timeout_ms=settings.redis_operation_timeout_ms,
                key_prefix=settings.redis_key_prefix,
            )
            clients.append(embedding)
        chat, llm_reranker, qa_generator, practice_provider = None, None, None, None
        grading_provider, course_generator, course_tutor_generator = None, None, None
        course_application_generator = None
        llm_config = resolve_llm_config(settings)
        if llm_config.configured:
            model = create_chat_model(settings, temperature=0.2)
            clients.append(ChatModelCloser(model))
            chat = MeteredChat(model)
            if settings.course_enabled:
                course_model = chat_model_from_config(
                    llm_config, temperature=0.3, max_tokens=4500,
                    timeout_seconds=settings.course_provider_timeout_seconds,
                )
                clients.append(ChatModelCloser(course_model))
                teaching_identity = {
                    "provider": llm_config.provider, "model": llm_config.model,
                    "endpoint_hash": text_hash(llm_config.base_url),
                }
                reviewer = TeachingReviewer(
                    MeteredChat(
                        course_model.bind(max_tokens=1200, temperature=0),
                        purpose="course_teaching_review", output_upper=1200,
                    ),
                    model_configuration={**teaching_identity, "temperature": 0},
                )
                course_generator = CourseGenerator(
                    MeteredChat(course_model.bind(max_tokens=3000), purpose="course_outline", output_upper=3000),
                    MeteredChat(course_model, purpose="course_lesson", output_upper=4500),
                    timeout_seconds=settings.course_provider_timeout_seconds,
                    model_configuration={"provider": llm_config.provider, "model": llm_config.model,
                                         "endpoint_hash": text_hash(llm_config.base_url), "temperature": 0.3},
                    reviewer=reviewer,
                )
                course_tutor_generator = CourseTutorGenerator(
                    MeteredChat(course_model.bind(max_tokens=1500), purpose="course_tutor", output_upper=1500),
                    timeout_seconds=settings.course_provider_timeout_seconds,
                    model_configuration={"provider": llm_config.provider, "model": llm_config.model,
                                         "endpoint_hash": text_hash(llm_config.base_url), "temperature": 0.3},
                )
                course_application_generator = CourseApplicationGenerator(
                    MeteredChat(
                        course_model.bind(max_tokens=4096),
                        purpose="course_application_generate", output_upper=4096,
                    ),
                    MeteredChat(
                        course_model.bind(max_tokens=1600, temperature=0),
                        purpose="course_application_feedback", output_upper=1600,
                    ),
                    timeout_seconds=settings.course_provider_timeout_seconds,
                )
            # Registry profiles share these output/context bounds. The job
            # additionally checks its pinned bounds before any practice call.
            practice_limits = PipelineConfig()
            practice_model = model.bind(max_tokens=practice_limits.output_token_reserve)
            practice_provider = LangChainPracticeProvider(
                MeteredChat(
                    practice_model,
                    purpose="practice_generation",
                    output_upper=practice_limits.output_token_reserve,
                ),
                semantic_llm=MeteredChat(
                    practice_model,
                    purpose="practice_validation",
                    output_upper=practice_limits.output_token_reserve,
                ),
                output_token_limit=practice_limits.output_token_reserve,
                model_context_window=practice_limits.model_context_window,
                model_configuration={
                    "provider": llm_config.provider,
                    "model": llm_config.model,
                    "endpoint_hash": text_hash(llm_config.base_url),
                    "temperature": 0.2,
                },
            )
            grading_configuration = grading_model_configuration(settings)
            grading_model = model.bind(
                max_tokens=settings.practice_grading_output_tokens
            )
            grading_provider = LangChainShortAnswerProvider(
                MeteredChat(
                    grading_model,
                    purpose="practice_grading",
                    output_upper=settings.practice_grading_output_tokens,
                ),
                output_token_limit=settings.practice_grading_output_tokens,
                model_context_window=settings.practice_grading_context_window,
                model_configuration=grading_configuration,
            )
            qa_generator = LangChainQaGenerator(
                MeteredChat(model, purpose="qa_answer"),
                rewrite_llm=MeteredChat(model, purpose="qa_rewrite"),
                semantic_llm=MeteredChat(model, purpose="qa_validate"),
                model_configuration={
                    "provider": llm_config.provider,
                    "model": llm_config.model,
                    "endpoint_hash": text_hash(llm_config.base_url),
                    "temperature": 0.2,
                },
            )
            ranking_config = llm_reranker_config(settings)
            ranking_model = model.bind(
                max_tokens=ranking_config.llm.max_output_tokens, temperature=0
            )
            llm_reranker = LLMReranker(
                MeteredChat(
                    ranking_model,
                    purpose="reranker",
                    output_upper=ranking_config.llm.max_output_tokens,
                ),
                ranking_config,
            )
        web = None
        if settings.enable_web_search and settings.tavily_api_key:
            client = MeteredFetchClient()
            clients.append(client)
            web = WebEvidenceProvider(
                TavilySearchClient(
                    settings.tavily_api_key, client=MeteredStageHTTP("search", 20)
                ),
                SafeWebFetcher(client=client),
                store,
            )
        reranker = None
        if settings.reranker_base_url and settings.reranker_model:
            config = RerankerConfig(
                provider=settings.reranker_model,
                endpoint=settings.reranker_base_url,
                model_revision=settings.reranker_model_revision,
                license=settings.reranker_license,
            )
            reranker = RemoteReranker(
                config,
                api_key=settings.reranker_api_key,
                client=MeteredStageHTTP("reranker", config.timeout_seconds),
            )
        engine = RagEngine(
            store,
            embedding,
            LangChainQuizGenerator(chat) if chat else None,
            reauthorize_scope,
            web_provider=web,
            reranker=reranker,
            llm_reranker=llm_reranker,
            qa_generator=qa_generator,
        )
        archive = settings.legacy_source_archive
        checksum = settings.legacy_source_archive_sha256
        if archive and checksum and chat:
            engine.configure_legacy_baseline(
                source_archive=archive,
                archive_sha256=checksum,
                source_commit=settings.legacy_source_commit,
                llm=chat,
            )
        return Runtime(
            engine=engine,
            report_generator=ConfiguredReportGenerator(chat) if chat else None,
            clients=clients,
            practice_provider=practice_provider,
            grading_provider=grading_provider,
            course_generator=course_generator,
            course_tutor_generator=course_tutor_generator,
            course_application_generator=course_application_generator,
        )
    except BaseException:
        # Client constructors do not make network calls. A failed configuration
        # must at least release the exclusive persistent-index owner lock.
        store.close()
        raise
