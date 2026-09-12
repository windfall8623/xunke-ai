"""循课 - 后端配置"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    data_dir: str = "./data"
    web_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:18080",
    ]
    cookie_secure: bool = False
    session_days: int = Field(default=7, ge=1, le=30)
    auth_rate_limit: int = 20
    legacy_link_enabled: bool = False
    email_registration_enabled: bool = True
    email_code_secret: str = Field(default="", repr=False)
    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_security: str = "ssl"
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from_email: str = ""
    smtp_from_name: str = "循课"
    smtp_timeout_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    email_send_cooldown_seconds: int = Field(default=60, ge=60)
    email_send_max_per_email_per_day: int = Field(default=5, ge=1)
    email_send_max_per_ip_per_hour: int = Field(default=10, ge=1)
    email_send_daily_limit: int = Field(default=100, ge=1)
    quiz_min_questions: int = 3
    quiz_max_questions: int = 10
    practice_enabled: bool = False
    course_enabled: bool = False
    course_provider_timeout_seconds: int = Field(default=120, ge=10, le=300)
    course_job_deadline_seconds: int = Field(default=300, ge=30, le=1800)
    practice_short_answer_enabled: bool = False
    practice_grading_output_tokens: int = Field(default=2048, ge=1, le=12000)
    practice_grading_context_window: int = Field(default=32768, ge=13000)
    practice_grading_profile_path: str = ""
    practice_grading_profile_hash: str = ""
    job_lease_seconds: int = 60
    job_heartbeat_seconds: int = 15
    job_max_attempts: int = 2
    job_deadline_seconds: int = 180
    job_queue_ttl_seconds: int = 900
    provider_timeout_seconds: int = 45
    user_daily_llm_calls: int = 200
    global_daily_llm_calls: int = 2000
    eval_daily_llm_calls: int = 2000
    eval_worker_token: str = ""
    eval_judge_config_path: str = ""
    rag_pipeline_id: str = "dense-v1"
    embedding_dimensions: int = 1024
    reranker_base_url: str = ""
    reranker_api_key: str = ""
    reranker_model: str = ""
    reranker_model_revision: str = ""
    reranker_license: str = ""
    reranker_llm_max_input_tokens: int = Field(default=12000, ge=1024, le=30000)
    reranker_llm_max_output_tokens: int = Field(default=512, ge=256, le=512)
    reranker_llm_timeout_seconds: float = Field(default=90, gt=0, le=180)
    pricing_version: str = "unconfigured"
    pricing_usd_to_cny: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    llm_input_cny_per_million: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    llm_output_cny_per_million: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    llm_cache_read_cny_per_million: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    llm_cache_write_cny_per_million: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    embedding_cny_per_million: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    rerank_call_cny: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    search_call_cny: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    image_call_cny: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    production_daily_cost_cny: float = 100
    global_daily_cost_cny: float = 1000
    eval_ingest_daily_cost_cny: float = 20
    eval_daily_cost_cny: float = 200
    legacy_source_archive: str = ""
    legacy_source_archive_sha256: str = ""
    legacy_source_commit: str = "7302ad2"
    debug_retention_days: int = 30
    eval_retention_days: int = 90

    @property
    def session_cookie_name(self) -> str:
        return "__Host-xunke_session" if self.cookie_secure else "xunke_session"

    @model_validator(mode="after")
    def secure_deployment(self):
        import re

        if not re.fullmatch(r"[a-zA-Z0-9_]+", self.mysql_database):
            raise ValueError("MYSQL_DATABASE must be an SQL identifier")
        if self.mysql_charset != "utf8mb4":
            raise ValueError("MYSQL_CHARSET must be utf8mb4")
        if self.app_env == "production":
            if not self.cookie_secure or any(
                not origin.startswith("https://") for origin in self.web_origins
            ):
                raise ValueError(
                    "Production requires Secure cookies and HTTPS WEB_ORIGINS"
                )
            if (
                self.jwt_secret == "change-me-in-production"
                or len(self.eval_worker_token) < 32
            ):
                raise ValueError(
                    "Production requires unique JWT_SECRET and EVAL_WORKER_TOKEN"
                )
            if self.mysql_auto_init:
                raise ValueError(
                    "Run migrations separately; MYSQL_AUTO_INIT must be false in production"
                )
            if self.redis_enabled and len(self.redis_password) < 32:
                raise ValueError(
                    "Production requires an independent REDIS_PASSWORD of at least 32 characters"
                )
        if self.redis_enabled and not self.redis_password:
            raise ValueError("REDIS_ENABLED requires REDIS_PASSWORD")
        if self.vector_backend == "qdrant" and not self.vector_projection_registry_required:
            raise ValueError("Qdrant requires VECTOR_PROJECTION_REGISTRY_REQUIRED=true")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", self.vector_target_revision):
            raise ValueError("VECTOR_TARGET_REVISION must be a short storage revision")
        if self.query_embedding_cache_enabled and not self.redis_cache_password:
            raise ValueError("Query embedding cache requires an independent REDIS_CACHE_PASSWORD")
        if self.query_embedding_cache_enabled and (
            self.redis_cache_password == self.redis_password
            or self.app_env == "production" and len(self.redis_cache_password) < 32
        ):
            raise ValueError("Query cache needs a distinct password of at least 32 characters in production")
        return self

    # Chat generation: choose one provider explicitly. Existing deployments that
    # only set DEEPSEEK_* keep their original behavior.
    llm_provider: Literal["deepseek", "anthropic", "openai_compatible"] = "deepseek"

    # Native Anthropic Messages API (Claude); independent of embedding and judge.
    anthropic_api_key: str = Field(default="", repr=False)
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-4-6"

    # Explicit OpenAI-compatible gateway; never discover OPENAI_* implicitly.
    llm_api_key: str = Field(default="", repr=False)
    llm_base_url: str = ""
    llm_model: str = ""

    # DeepSeek (backward-compatible)
    deepseek_api_key: str = "sk-xxx"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Tavily (Web Search)
    tavily_api_key: str = ""
    enable_web_search: bool = True

    # DashScope (百炼 Embedding，用于知识库 RAG)
    dashscope_api_key: str = ""
    dashscope_embedding_model: str = "text-embedding-v4"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 知识库 / 向量存储
    chroma_persist_dir: str = "./data/chroma"
    kb_upload_dir: str = "./data/uploads"
    kb_max_documents_per_user: int = 10
    kb_max_file_size_mb: int = 10
    kb_chunk_size: int = 1000
    kb_chunk_overlap: int = 150
    kb_retrieve_top_k: int = 4

    # 题目配图（DashScope 千问-文生图 qwen-image）
    dashscope_image_model: str = "qwen-image-2.0"
    # 生图专用 API Key（仅官方 DashScope 地址允许回退使用 dashscope_api_key）。
    # 注意：部分 sk-ws- 开头的工作空间 Key 按用途限定权限范围，Embedding 与生图可能需要各自的 Key。
    dashscope_image_api_key: str = ""
    # 图像生成使用的原生 DashScope API 地址（与 OpenAI 兼容模式的 dashscope_base_url 不同）
    # 仅官方 DashScope Embedding 地址允许派生；第三方 Embedding 必须独立配置图片地址。
    dashscope_image_base_url: str = ""
    image_gen_size: str = "512*512"
    image_gen_daily_limit: int = 20
    image_gen_max_concurrency: int = 5

    # 腾讯云 COS（用于持久化存储 AI 生成的题目配图）
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = ""
    cos_bucket: str = ""
    cos_upload_prefix: str = "quiz-images/"
    # 可选：自定义访问域名（如 CDN 加速域名），留空则使用 COS 默认域名
    cos_domain: str = ""

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 43200  # 30 天

    # 微信小程序
    wechat_app_id: str = ""
    wechat_app_secret: str = ""

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "zhixue_ai"
    mysql_charset: str = "utf8mb4"
    mysql_pool_minsize: int = 1
    mysql_pool_maxsize: int = 10
    mysql_auto_init: bool = True

    # Redis（可选）：共享短窗限流与任务事件通知的加速组件。
    # 关闭或故障时全部功能退回原 SQL 路径；启用必须提供独立密码。
    redis_enabled: bool = False
    redis_host: str = "redis"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: str = Field(default="", repr=False)
    redis_tls: bool = False
    redis_key_prefix: str = "xunke:development:v1"
    redis_connect_timeout_ms: int = Field(default=100, ge=10, le=5000)
    redis_command_timeout_ms: int = Field(default=100, ge=10, le=5000)
    redis_operation_timeout_ms: int = Field(default=200, ge=20, le=10000)
    redis_max_connections: int = Field(default=16, ge=1, le=256)

    # Redis 共享突发门槛：只统计进入后续 SQL 检查的请求，SQL 硬限制始终执行。
    redis_rate_limit_enabled: bool = False
    auth_burst_window_seconds: int = Field(default=60, ge=1, le=3600)
    auth_burst_max_per_ip: int = Field(default=20, ge=1)
    auth_burst_max_per_account: int = Field(default=10, ge=1)
    email_burst_window_seconds: int = Field(default=60, ge=1, le=3600)
    email_burst_max_per_ip: int = Field(default=10, ge=1)
    email_burst_max_per_account: int = Field(default=3, ge=1)

    # 任务阶段 SSE：默认关闭；打开后端点仍要求业务授权，通知丢失可补读。
    task_events_enabled: bool = False
    task_event_retention_hours: int = Field(default=24, ge=1)
    task_event_sync_seconds: int = Field(default=15, ge=1, le=120)
    task_event_max_connection_seconds: int = Field(default=900, ge=30, le=3600)

    # 向量后端选择：chroma（默认轻量）或 qdrant（服务化共享检索）。
    vector_backend: Literal["chroma", "qdrant"] = "chroma"
    vector_target_revision: str = "legacy-v1"
    vector_projection_registry_required: bool = False
    rag_worker_role: Literal["owner", "writer", "generation"] = "owner"
    qdrant_generation_workers: int = Field(default=2, ge=1, le=8)

    # Qdrant 单节点：读写双 key 分离；API 与 eval-scorer 不持有向量库凭据。
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection_prefix: str = "xunke_dense"
    qdrant_api_key: str = Field(default="", repr=False)
    qdrant_read_only_api_key: str = Field(default="", repr=False)
    qdrant_search_timeout_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)
    qdrant_write_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    qdrant_rpc_concurrency: int = Field(default=4, ge=1, le=64)
    qdrant_batch_size: int = Field(default=128, ge=1, le=1024)
    qdrant_max_request_bytes: int = Field(default=2097152, ge=65536)
    qdrant_vector_on_disk: bool = True
    qdrant_hnsw_m: int = Field(default=16, ge=4, le=64)
    qdrant_hnsw_ef_construct: int = Field(default=128, ge=16, le=1000)
    qdrant_hnsw_ef_search: int = Field(default=64, ge=16, le=1000)

    # Query-only cache, isolated from the noeviction rate-limit instance.
    query_embedding_cache_enabled: bool = False
    query_embedding_cache_ttl_seconds: int = Field(default=86400, ge=1, le=604800)
    embedding_model_revision: str = ""
    redis_cache_host: str = "redis-cache"
    redis_cache_port: int = Field(default=6379, ge=1, le=65535)
    redis_cache_db: int = Field(default=0, ge=0, le=15)
    redis_cache_password: str = Field(default="", repr=False)
    redis_cache_tls: bool = False

    # Log
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
