"""Server-owned observations for the pure JSON scorer, never dataset assertions."""

import copy

from pydantic import ValidationError
from rag_eval.contracts import canonical_hash

from app.core.db import fetch_one
from app.core.values import load
from app.models.eval_contracts import AnswerGradingSample, PracticeGenerationSample
from app.practice.contracts import PracticeArtifact, PracticePayload
from app.practice.identity import canonical_question_version
from app.practice.validation import validate_practice_payload
from app.rag.contracts import BuildResult, ExecutionContext, ResolvedScope, stable_hash
from app.rag.errors import RagError, SourceUnavailable

RESERVED_OBSERVATIONS = (
    "practice_validation",
    "grading_context",
    "semantic_reviews",
    "grader_calibrated",
    "calibration_profile_hash",
    "source_validation",
)


class _PinnedBuilds:
    """Read-only SQL artifact view; never constructs a vector/index owner."""

    def __init__(self, builds):
        self.builds = builds

    def read_build(self, source):
        build = self.builds.get(source.index_build_id)
        fields = (
            "owner_id",
            "namespace",
            "doc_id",
            "document_version_id",
            "parse_artifact_id",
            "index_build_id",
            "attempt_id",
            "source_sha256",
            "canonical_text_hash",
        )
        if build is None or any(
            getattr(build, key) != getattr(source, key) for key in fields
        ):
            raise SourceUnavailable("Scoring build differs from its authorized source")
        if build.profile.profile_id != source.index_profile_id or (
            source.index_profile_hash
            and source.index_profile_hash != build.index_profile_hash
        ):
            raise SourceUnavailable("Scoring index profile changed")
        return build


async def scoring_store(sample, artifact, scope_data, *, conn=None):
    """Use only after the existing run/source authorization locks are acquired."""
    if (
        sample.get("case_type") != "answer_grading"
        or artifact.get("status") != "completed"
    ):
        return None
    scope = ResolvedScope.model_validate(scope_data)
    builds = {}
    for source in scope.documents:
        row = await fetch_one(
            "SELECT manifest_json FROM kb_index_builds WHERE build_id=%s AND owner_id=%s AND status='ready'",
            (source.index_build_id, scope.owner_id),
            conn=conn,
        )
        if not row:
            raise SourceUnavailable("The frozen scoring source build is unavailable")
        builds[source.index_build_id] = BuildResult.model_validate(
            load(row["manifest_json"])
        )
    return _PinnedBuilds(builds)


def scoring_observations(sample, artifact, config, scope_data, *, store, reviews=()):
    """Caller must authorize the source scope before reading the immutable store."""
    result = copy.deepcopy(config)
    for key in RESERVED_OBSERVATIONS:
        result.pop(key, None)
    result["semantic_reviews"] = copy.deepcopy(list(reviews))
    kind = sample.get("case_type")
    if kind not in {"practice_generation", "answer_grading"}:
        return result
    # Minimum evaluation has no independent calibration approval. A user-provided
    # config or a plausible-looking model score cannot upgrade this observation.
    result["grader_calibrated"] = False
    result["calibration_profile_hash"] = None
    if artifact.get("status") != "completed" or not scope_data:
        return result
    scope = ResolvedScope.model_validate(scope_data)
    if scope.namespace != "evaluation" and not scope.namespace.startswith(
        "evaluation:"
    ):
        return result
    try:
        if kind == "practice_generation":
            from app.rag.practice_evaluation import evaluation_practice_spec

            raw = artifact.get("practice")
            private = PracticeArtifact.model_validate(raw)
            request = PracticeGenerationSample.model_validate(sample)
            if (
                private.mode != "evaluation"
                or private.scope_fingerprint != scope.fingerprint
            ):
                return result
            context = ExecutionContext(
                mode="evaluation",
                run_id=private.run_id,
                storage_namespace=scope.namespace,
            )
            spec = evaluation_practice_spec(request.spec, context, request.sample_id)
            payload = PracticePayload.model_validate(
                {key: raw[key] for key in ("title", "summary", "questions")}
            )
            errors = validate_practice_payload(payload, spec, private.evidence_pack)
            result["practice_validation"] = {
                "artifact_hash": canonical_hash(raw),
                "question_results": [
                    {
                        "question_id": question.id,
                        "question_hash": canonical_hash(raw_question),
                        "schema_valid": not errors,
                    }
                    for question, raw_question in zip(
                        private.questions, raw["questions"], strict=True
                    )
                ],
                "question_versions": {
                    question.id: canonical_question_version(
                        question, private.evidence_pack
                    )
                    for question in private.questions
                },
                "rubric_hashes": {
                    question.id: stable_hash(question.rubric.model_dump(mode="json"))
                    for question in private.questions
                },
            }
        else:
            from app.rag.practice_evaluation import grading_evidence_pack

            request = AnswerGradingSample.model_validate(sample)
            pack = grading_evidence_pack(request, scope, store)
            result["grading_context"] = {
                "sample_id": request.sample_id,
                "question_hash": canonical_hash(sample["question"]),
                "question_version": canonical_question_version(request.question, pack),
                "rubric_hash": stable_hash(
                    request.question.rubric.model_dump(mode="json")
                ),
                "response_hash": stable_hash(request.answer.model_dump(mode="json")),
                "scope_fingerprint": scope.fingerprint,
                "evidence_pack": pack.model_dump(mode="json"),
            }
    except (ValidationError, RagError, ValueError, KeyError, TypeError):
        # An invalid private payload is not a positive schema/source observation.
        # The scorer retains unknown denominators or reports the explicit failure.
        return result
    return result
