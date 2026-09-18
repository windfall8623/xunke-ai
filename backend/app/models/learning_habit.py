"""Effective learning-day habits and rest preferences (C02)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.learning.contracts import IanaTimezone


class HabitRestPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    weekly_rest_days: list[int] = Field(default_factory=list, max_length=7)
    effective_from: date

    @model_validator(mode="after")
    def unique_iso_weekdays(self):
        if any(day < 0 or day > 6 for day in self.weekly_rest_days):
            raise ValueError("weekly_rest_days must be ISO weekdays 0-6")
        if len(set(self.weekly_rest_days)) != len(self.weekly_rest_days):
            raise ValueError("weekly_rest_days must be unique")
        return self


class HabitRestPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    weekly_rest_days: list[int] = Field(default_factory=list, max_length=7)
    effective_from: date | None = None


class HabitDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_date: date
    kind: Literal["learning", "rest", "empty", "today_pending"]
    activity_count: int = Field(ge=0)


class HabitMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_days: int
    reached: bool
    reached_on: date | None = None


class LearningHabitView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_date: date
    timezone: IanaTimezone
    effective_streak_days: int = Field(ge=0)
    rest_days_in_streak: int = Field(ge=0)
    effective_days_total: int = Field(ge=0)
    last_effective_local_date: date | None = None
    recent_days: list[HabitDay] = Field(default_factory=list, max_length=28)
    milestones: list[HabitMilestone] = Field(default_factory=list, max_length=5)
    rule_version: Literal["learning-habits-v1"] = "learning-habits-v1"
