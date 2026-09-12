"""跨页面任务通知的公开视图：只含状态与定位字段，不含结果正文。"""

from pydantic import Field

from app.rag.contracts import Contract


class TaskOverviewItem(Contract):
    task_id: str
    kind: str
    status: str
    stage: str = "queued"
    error_code: str | None = None
    # 展示标题：课程主题/课时名/资料名/练习输入摘要，按 kind 取用。
    title: str | None = None
    course_id: str | None = None
    course_title: str | None = None
    lesson_id: str | None = None
    quiz_id: str | None = None
    doc_id: str | None = None
    created_at: str
    updated_at: str


class ProcessingDocument(Contract):
    doc_id: str
    file_name: str
    status: str = "processing"


class TaskOverviewView(Contract):
    tasks: list[TaskOverviewItem] = Field(default_factory=list)
    documents: list[ProcessingDocument] = Field(default_factory=list)
