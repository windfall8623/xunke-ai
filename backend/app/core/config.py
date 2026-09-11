"""知学 AI - 后端配置"""

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
    quiz_min_questions: int = 3
    quiz_max_questions: int = 10
    practice_enabled: bool = False
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
        return "__Host-zhixue_session" if self.cookie_secure else "zhixue_session"

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

    # Log
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
