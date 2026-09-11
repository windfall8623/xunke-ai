"""通用响应模型"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    error_code: str | None = None

    @classmethod
    def success(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def error(cls, code: int, message: str) -> "ApiResponse":
        return cls(code=code, message=message, data=None)
