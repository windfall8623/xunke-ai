"""The single adapter from learning services to historical V1 QA sources."""

from app.core.errors import AppError, conflict
from app.learning.contracts import QaPracticeContext
from app.models.sources import PublicResolvedScope
from app.models.study import StudyQaPracticeContextView
from app.services import qa_read


async def load_answer(owner_id: int, answer_id: str, *, conn=None):
    """Return the authorized answer, its complete historical scope and artifact."""
    row, scope = await qa_read.owned_answer(owner_id, answer_id, conn=conn)
    artifact = qa_read.checked_artifact(row, scope)
    return row, scope, artifact


def _practice_facts(artifact):
    if artifact.answer_status not in {"answered", "partial"}:
        raise conflict("qa_not_practiceable", "此回答暂不能直接转为练习")
    return [
        block
        for block in artifact.blocks
        if block.kind == "fact" and block.citation_refs
    ]


async def load_context(
    owner_id: int, answer_id: str, block_ids: list[str], *, conn=None
) -> QaPracticeContext:
    """Select checked facts while retaining the answer's complete original scope."""
    row, scope, artifact = await load_answer(owner_id, answer_id, conn=conn)
    facts = _practice_facts(artifact)
    available = {block.block_id for block in facts}
    if (
        not block_ids
        or len(block_ids) > 12
        or len(set(block_ids)) != len(block_ids)
        or not set(block_ids) <= available
    ):
        raise AppError(
            422, "invalid_qa_fact_blocks", "请选择此回答中有引用依据的事实块"
        )
    selected = [block for block in facts if block.block_id in block_ids]
    cited = {ref for block in selected for ref in block.citation_refs}
    return QaPracticeContext(
        owner_id=owner_id,
        answer_id=row["answer_id"],
        session_id=row["session_id"],
        scope_revision=row["scope_revision"],
        artifact_hash=row["artifact_hash"],
        scope=scope,
        retrieval_query=artifact.retrieval_query,
        selected_fact_blocks=selected,
        evidence_ids=[
            item.evidence_id for item in artifact.evidence if item.evidence_id in cited
        ],
    )


async def practice_context_view(
    owner_id: int, answer_id: str
) -> StudyQaPracticeContextView:
    row, scope, artifact = await load_answer(owner_id, answer_id)
    return StudyQaPracticeContextView(
        answer_id=row["answer_id"],
        session_id=row["session_id"],
        scope_revision=row["scope_revision"],
        answer_status=artifact.answer_status,
        scope=PublicResolvedScope.from_scope(scope),
        retrieval_query=artifact.retrieval_query,
        fact_blocks=_practice_facts(artifact),
    )
