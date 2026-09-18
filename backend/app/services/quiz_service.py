"""HTTP/application wrapper. Only the RAG owner worker performs generation."""

from app.core.config import get_settings
from app.core.db import transaction
from app.core.errors import AppError, conflict, not_found
from app.core.exceptions import ContentFilterError
from app.core.security import check_content
from app.core.values import digest, dump, load
from app.rag.contracts import QuizSpec, ResolvedScope
from app.rag.scope import normalize_spec
from app.services import job_service, learning_service


def parse_quiz_request(request):
    """Read a private envelope or a legacy flat request without leaking extras."""
    from app.services.learning_quiz_service import LearningQuizContext

    if not isinstance(request, dict):
        raise ValueError("A quiz job request must be an object")
    metadata = {"generate_images", "review_of_quiz_id", "pipeline_id"}
    if "spec" in request:
        if set(request) - {"spec", "learning_context", *metadata}:
            raise ValueError("Unsupported quiz envelope fields")
        spec = normalize_spec(request["spec"])
        learning_context = request.get("learning_context")
        return spec, (
            LearningQuizContext.model_validate(learning_context)
            if learning_context is not None
            else None
        )
    spec_fields = {*QuizSpec.model_fields, "doc_id"}
    if set(request) - spec_fields - metadata:
        raise ValueError("Unsupported legacy quiz request fields")
    return normalize_spec(
        {key: value for key, value in request.items() if key in spec_fields}
    ), None


def resolved_quiz_request(actor, spec, scope):
    """Validate shared fixed-source generation inputs without opening a job."""
    spec = normalize_spec(spec)
    scope = ResolvedScope.model_validate(scope)
    if scope.owner_id != actor.owner_id or scope.namespace != "production":
        raise not_found()
    settings = get_settings()
    if (
        not settings.quiz_min_questions
        <= spec.question_count
        <= settings.quiz_max_questions
    ):
        raise AppError(422, "invalid_question_count", "题量超出允许范围")
    if not check_content(spec.user_input):
        raise ContentFilterError("输入内容包含不支持的内容，请更换学习主题")
    request = {
        "spec": spec.model_dump(mode="json"),
        "generate_images": False,
        "review_of_quiz_id": None,
        "pipeline_id": settings.rag_pipeline_id,
    }
    return spec, scope, request


async def enqueue_resolved_quiz(
    actor, spec, scope, key, *, learning_context=None, conn=None, request_hash=None,
    before_authorize=None,
):
    """Enqueue an authorized fixed scope; never resolve an active source build."""
    from app.services import learning_quiz_service
    from app.services.source_service import reauthorize_scope

    spec, scope, request = resolved_quiz_request(actor, spec, scope)
    if learning_context is not None:
        learning_context = learning_quiz_service.validate_learning_context(
            spec, scope, learning_context
        )
        request["learning_context"] = learning_context.model_dump(mode="json")
        computed_hash = learning_quiz_service.learning_request_hash(
            spec, learning_context
        )
    else:
        computed_hash = digest(
            dump({"spec": request["spec"], "scope": scope.model_dump(mode="json")})
        )
    # Inserting the durable key precedes space/source locks, matching worker and
    # cleanup order. Reauthorize the actual saved envelope on a racing replay.
    request_hash = request_hash or computed_hash

    async def enqueue(conn):
        job = await job_service.enqueue_job(
            actor.owner_id,
            "quiz",
            request,
            key,
            scope=scope.model_dump(mode="json"),
            request_hash=request_hash,
            conn=conn,
        )
        job = await job_service.existing_job(
            actor.owner_id, "quiz", key, request_hash, conn=conn, lock=True
        )
        if before_authorize is not None:
            # Course callers acquire their aggregate lock after the job and
            # before any source locks, matching publication and revocation.
            await before_authorize(job, conn)
        if learning_context is not None:
            await learning_quiz_service.authorize_job(actor.owner_id, job, conn=conn)
        else:
            saved_spec, saved_context = parse_quiz_request(job["request"])
            saved_scope = ResolvedScope.model_validate(job["scope"])
            if saved_context is not None or saved_spec != spec or saved_scope != scope:
                raise conflict("quiz_scope_changed", "练习请求与已保存的来源范围不一致")
            await reauthorize_scope(saved_scope, conn=conn)
        return job
    if conn is not None:
        # A course assessment inserts its separate association before this
        # caller-owned transaction commits; no private envelope extras are used.
        return await enqueue(conn)
    async with transaction() as conn:
        job = await enqueue(conn)
    return await job_service.get_task(actor.owner_id, job["task_id"])


async def resolved_review_request(
    actor, quiz_id, question_count, difficulty, *, conn=None
):
    """Prepare a review from saved answers and its original frozen sources."""
    from app.services.source_service import reauthorize_scope

    original = await learning_service.owned_quiz(
        actor.owner_id, quiz_id, conn=conn
    )
    detail = await learning_service.get_detail(actor.owner_id, quiz_id, conn=conn)
    wrong_ids = {
        answer["question_id"]
        for answer in detail["answer_records"]
        if not answer["is_correct"]
    }
    if not wrong_ids:
        raise conflict("no_weak_points", "请先完成练习，或选择新的学习主题")
    if (
        original["source_status"] == "legacy_unverified"
        or not original["user_input"]
    ):
        raise conflict(
            "review_source_unverified",
            "旧题缺少可核验来源，请重新选择学习主题和资料",
        )
    raw_scope = load(original["source_scope_json"])
    if raw_scope is None:
        if original["source_policy"] != "topic":
            raise conflict(
                "review_source_unverified", "原练习缺少可核验的资料范围"
            )
        scope = ResolvedScope(owner_id=actor.owner_id, namespace="production")
    else:
        scope = ResolvedScope.model_validate(raw_scope)
    if (original["source_policy"] == "topic") == bool(scope.documents):
        raise conflict("review_source_unverified", "原练习的来源策略与资料范围不一致")
    await reauthorize_scope(scope, conn=conn)
    weak = [
        question.get("knowledge_point") or question["stem"]
        for question in load(original["questions_json"], [])
        if question["id"] in wrong_ids
    ]
    if not weak:
        raise conflict("no_weak_points", "原练习缺少可用的错题记录")
    requested_scope = None
    if original["source_policy"] != "topic":
        if not scope.documents:
            raise conflict(
                "review_source_unverified", "原练习缺少可核验的资料范围"
            )
        requested_scope = {
            "documents": [
                {
                    "doc_id": source.doc_id,
                    "section_ids": source.section_ids,
                    "section_catalog_revision": source.section_catalog_revision,
                }
                for source in scope.documents
            ]
        }
    spec = QuizSpec(
        user_input=original["user_input"],
        objective_titles=weak[:10],
        question_count=question_count,
        difficulty=difficulty,
        source_policy=original["source_policy"],
        scope=requested_scope,
    )
    spec, scope, request = resolved_quiz_request(actor, spec, scope)
    request["review_of_quiz_id"] = quiz_id
    return spec, scope, request


async def create_quiz_job(actor, body, key):
    if (
        not get_settings().quiz_min_questions
        <= body.question_count
        <= get_settings().quiz_max_questions
    ):
        raise AppError(422, "invalid_question_count", "题量超出允许范围")
    semantic_request = body.model_dump(mode="json", exclude_none=True)
    request_hash = digest(dump(semantic_request))
    # Check retry identity before resolving current active builds.
    old = await job_service.existing_job(actor.owner_id, "quiz", key, request_hash)
    if old:
        return await job_service.get_task(actor.owner_id, old["task_id"])
    scope = None
    if body.review_of_quiz_id:
        spec, resolved_scope, _ = await resolved_review_request(
            actor, body.review_of_quiz_id, body.question_count, body.difficulty
        )
        scope = resolved_scope.model_dump(mode="json")
    else:
        raw = {
            key: value
            for key, value in semantic_request.items()
            if key not in ("generate_images", "review_of_quiz_id")
        }
        spec = normalize_spec(raw)
        if spec.scope:
            from app.services.source_service import resolve_scope

            scope = (await resolve_scope(actor, spec.scope)).model_dump(mode="json")
    if not check_content(spec.user_input):
        raise ContentFilterError("输入内容包含不支持的内容，请更换学习主题")
    request = {
        **spec.model_dump(mode="json"),
        "generate_images": body.generate_images,
        "review_of_quiz_id": body.review_of_quiz_id,
        "pipeline_id": get_settings().rag_pipeline_id,
    }
    job = await job_service.enqueue_job(
        actor.owner_id, "quiz", request, key, scope=scope, request_hash=request_hash
    )
    return await job_service.get_task(actor.owner_id, job["task_id"])
