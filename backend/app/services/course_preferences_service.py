"""Personal learning preferences (B05).

首次读取返回无模型默认值；只有 PATCH 才创建持久记录。降低难度只改变
解释与练习输入，不改变 A07 的成功标准，也不改写任何已结算成绩。
"""

from app.core.db import execute, fetch_one, transaction
from app.core.errors import conflict
from app.models.course_preferences import LearningPreferencesUpdate, LearningPreferencesView

DEFAULTS = LearningPreferencesView(
    revision=1,
    daily_minutes=20,
    daily_review_limit=1,
    difficulty="mixed",
    timezone="Asia/Shanghai",
)


async def get_preferences(owner):
    row = await fetch_one(
        "SELECT * FROM learning_user_preferences WHERE owner_id=%s", (owner,)
    )
    return _view(row) if row else DEFAULTS


async def update_preferences(owner, body: LearningPreferencesUpdate):
    async with transaction() as conn:
        row = await fetch_one(
            "SELECT * FROM learning_user_preferences WHERE owner_id=%s FOR UPDATE",
            (owner,),
            conn=conn,
        )
        if row is None:
            if body.expected_revision != 1:
                raise conflict("revision_conflict", "学习偏好已更新，请刷新后重试")
            await execute(
                "INSERT INTO learning_user_preferences(owner_id,daily_minutes,"
                "daily_review_limit,difficulty,timezone,revision) VALUES(%s,%s,%s,%s,%s,2)",
                (owner, body.daily_minutes, body.daily_review_limit, body.difficulty,
                 body.timezone),
                conn=conn,
            )
            revision = 2
        else:
            if row["revision"] != body.expected_revision:
                raise conflict("revision_conflict", "学习偏好已更新，请刷新后重试")
            await execute(
                "UPDATE learning_user_preferences SET daily_minutes=%s,daily_review_limit=%s,"
                "difficulty=%s,timezone=%s,revision=revision+1 WHERE owner_id=%s",
                (body.daily_minutes, body.daily_review_limit, body.difficulty, body.timezone,
                 owner),
                conn=conn,
            )
            revision = row["revision"] + 1
    return LearningPreferencesView(
        revision=revision,
        daily_minutes=body.daily_minutes,
        daily_review_limit=body.daily_review_limit,
        difficulty=body.difficulty,
        timezone=body.timezone,
    )


async def effective_preferences(owner):
    """今日推荐与任务冻结使用的当前生效值（未设置时为默认值）。"""
    return await get_preferences(owner)


def freeze_snapshot(prefs: LearningPreferencesView) -> dict:
    """新任务记录的偏好快照：重放任务沿用创建时的值。"""
    return {
        "preference_revision": prefs.revision,
        "daily_minutes": prefs.daily_minutes,
        "difficulty": prefs.difficulty,
    }


def _view(row) -> LearningPreferencesView:
    return LearningPreferencesView(
        revision=row["revision"],
        daily_minutes=row["daily_minutes"],
        daily_review_limit=row["daily_review_limit"],
        difficulty=row["difficulty"],
        timezone=row["timezone"],
    )
