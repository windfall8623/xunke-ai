"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import (
    auth,
    evaluation,
    feedback,
    health,
    internal_eval,
    knowledge,
    practice,
    practice_grading,
    practice_views,
    qa,
    quiz,
    report,
    study,
    user,
)
from app.core.config import get_settings
from app.core.db import close_mysql_pool, init_mysql, init_pool
from app.core.errors import AppError
from app.core.exceptions import (
    AuthenticationError,
    ContentFilterError,
    KnowledgeBaseError,
    QuizGenerationError,
    ReportGenerationError,
)
from app.models.common import ApiResponse
from app.rag.errors import RagError

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("app_starting", host=settings.app_host, port=settings.app_port)
    if settings.mysql_auto_init:
        await init_mysql()
    else:
        await init_pool()
    yield
    await close_mysql_pool()
    logger.info("app_shutting_down")


app = FastAPI(
    title="知学 AI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().web_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(quiz.router, prefix="/api/v1")
app.include_router(report.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(knowledge.eval_router, prefix="/api/v1")
app.include_router(qa.router, prefix="/api/v1")
app.include_router(study.router, prefix="/api/v1")
app.include_router(practice.router, prefix="/api/v1")
app.include_router(practice_grading.router, prefix="/api/v1")
app.include_router(practice_views.router, prefix="/api/v1")
app.include_router(evaluation.router, prefix="/api/v1")
app.include_router(internal_eval.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")


@app.exception_handler(RagError)
async def rag_error_handler(request: Request, exc: RagError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code * 10,
            "error_code": exc.code.lower(),
            "message": exc.message,
            "data": None,
        },
    )


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status,
        content={
            "code": exc.status * 10,
            "error_code": exc.code,
            "message": exc.message,
            "data": None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Validation failures must not echo passwords or private document contents.
    return JSONResponse(
        status_code=422,
        content={
            "code": 4220,
            "error_code": "validation_error",
            "message": "请求参数无效，请检查输入",
            "data": None,
        },
    )


# 全局异常处理
@app.exception_handler(AuthenticationError)
async def auth_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=401,
        content=ApiResponse.error(code=4010, message=str(exc)).model_dump(),
    )


@app.exception_handler(ContentFilterError)
async def content_filter_handler(request: Request, exc: ContentFilterError):
    return JSONResponse(
        status_code=400,
        content=ApiResponse.error(code=4000, message=str(exc)).model_dump(),
    )


@app.exception_handler(QuizGenerationError)
async def quiz_error_handler(request: Request, exc: QuizGenerationError):
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(code=5001, message=str(exc)).model_dump(),
    )


@app.exception_handler(ReportGenerationError)
async def report_error_handler(request: Request, exc: ReportGenerationError):
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(code=5002, message=str(exc)).model_dump(),
    )


@app.exception_handler(KnowledgeBaseError)
async def knowledge_base_error_handler(request: Request, exc: KnowledgeBaseError):
    return JSONResponse(
        status_code=400,
        content=ApiResponse.error(code=4001, message=str(exc)).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理：避免直接暴露裸的 "Internal Server Error"，并记录完整堆栈便于排查。"""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(
            code=5000, message="服务器内部错误，请稍后重试"
        ).model_dump(),
    )


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
