"""Public errors never carry provider messages, SQL, prompts or file paths."""


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def not_found():
    return AppError(404, "not_found", "资源不存在或无权访问")


def conflict(code="revision_conflict", message="内容已更新，请刷新后重试"):
    return AppError(409, code, message)