"""用户相关数据模型"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    code: str = Field(min_length=1, description="wx.login() 返回的 code")


class LoginResponse(BaseModel):
    token: str
    user: "UserBrief"


class UserBrief(BaseModel):
    id: int
    nickname: str
    avatar_url: str
    total_xp: int


class UserProfile(BaseModel):
    id: int
    nickname: str
    avatar_url: str
    total_xp: int
    quiz_count: int
    correct_count: int
    average_accuracy: int


class UpdateProfileRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)


class AvatarUploadResponse(BaseModel):
    avatar_url: str


class QuizHistoryItem(BaseModel):
    quiz_id: str
    title: str
    accuracy: float | None
    question_count: int
    answered_count: int
    revision: int
    status: str
    source_status: str
    images_status: str
    report_status: str
    created_at: str


class QuizHistoryList(BaseModel):
    items: list[QuizHistoryItem]
    total: int
    page: int
    page_size: int


class QuizDetailResponse(BaseModel):
    quiz_id: str
    title: str
    summary: str
    user_input: str | None = None
    questions: list  # raw JSON
    answer_records: list | None = None
    report: dict | None = None
    created_at: str
