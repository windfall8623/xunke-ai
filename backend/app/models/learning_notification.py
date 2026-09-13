"""Reminder preference and in-app reminder contracts (B07)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.learning.contracts import IanaTimezone


class LearningReminderPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    in_app_enabled: bool = False
    email_enabled: bool = False
    frequency: Literal["daily_due", "weekly"] = "weekly"
    local_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: IanaTimezone = "Asia/Shanghai"
    paused_until: str | None = None


class LearningReminderPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    in_app_enabled: bool
    email_enabled: bool
    frequency: Literal["daily_due", "weekly"] = "weekly"
    local_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: IanaTimezone = "Asia/Shanghai"
    paused_until: str | None = Field(default=None, min_length=1, max_length=64)


class LearningReminderView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminder_id: str
    kind: Literal["weekly_summary", "due_review", "course_event"]
    title: str
    body: str | None = None
    link_path: str | None = None
    due_at: str | None = None
    read_at: str | None = None
    created_at: str


class LearningReminderList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LearningReminderView]
    total: int


class LearningReminderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["read", "snooze"]
    send_after: str | None = Field(default=None, min_length=1, max_length=64)
