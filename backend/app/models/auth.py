from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_@.+-]+$")
    password: str = Field(min_length=10, max_length=128)

    @field_validator("account")
    @classmethod
    def normalize(cls, value):
        return value.lower()


class RegisterBody(LoginBody):
    nickname: str = Field(default="学习者", min_length=1, max_length=100)


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
