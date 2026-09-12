import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


EMAIL_PATTERN = (
    r"^[a-z0-9_+.-]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def normalize_email(value: str) -> str:
    """Keep mailbox matching explicit; never rewrite provider-specific aliases."""
    if not isinstance(value, str):
        raise ValueError("邮箱格式无效")
    email = value.strip().lower()
    local = email.partition("@")[0]
    if (
        len(email) > 100
        or len(local) > 64
        or not re.fullmatch(EMAIL_PATTERN, email)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
    ):
        raise ValueError("邮箱格式无效")
    return email


class UserView(BaseModel):
    id: int
    nickname: str
    avatar_url: str
    total_xp: int
    role: str = "learner"


class SessionView(BaseModel):
    user: UserView
    csrf_token: str
    recovery_code: str | None = None


class AuthCapabilitiesView(BaseModel):
    legacy_link_enabled: bool = False
    email_registration_enabled: bool = False
    email_verification_required: bool = True
    email_code_cooldown_seconds: int = 60


class EmailCodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=100, pattern=EMAIL_PATTERN)

    @field_validator("email", mode="before")
    @classmethod
    def normalize(cls, value):
        return normalize_email(value)


class EmailCodeView(BaseModel):
    message: str
    retry_after_seconds: int
    expires_in_seconds: int


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_@.+-]+$")
    password: str = Field(min_length=10, max_length=128)

    @field_validator("account", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class RegisterBody(LoginBody):
    account: str = Field(min_length=3, max_length=100, pattern=EMAIL_PATTERN)
    nickname: str = Field(default="学习者", min_length=1, max_length=100)
    verification_code: str = Field(
        min_length=6, max_length=6, pattern=r"^[0-9]{6}$", repr=False
    )

    @field_validator("account", mode="before")
    @classmethod
    def normalize_registration_account(cls, value):
        return normalize_email(value)


class RecoverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=3, max_length=100)
    recovery_code: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class BindBody(RegisterBody):
    code: str = Field(min_length=16, max_length=128)
