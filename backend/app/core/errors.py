"""Public errors never carry provider messages, SQL, prompts or file paths."""


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        # 唯一允许进入响应头的附加字段：限流类 429 的 Retry-After。
        self.retry_after_seconds = retry_after_seconds


def not_found():
    return AppError(404, "not_found", "资源不存在或无权访问")


def conflict(code="revision_conflict", message="内容已更新，请刷新后重试"):
    return AppError(409, code, message)


def rate_limited(retry_after_seconds: int | None = None) -> AppError:
    return AppError(
        429,
        "rate_limited",
        "请求过于频繁，请稍后再试",
        retry_after_seconds=retry_after_seconds,
    )
