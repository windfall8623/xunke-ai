"""Disjoint claim sets for one index writer and independent learning workers."""

GENERATION_KINDS = frozenset({"qa", "course_outline", "course_lesson", "course_tutor"})


def effective_role(settings, requested=None):
    role = requested or settings.rag_worker_role
    if settings.vector_backend == "chroma":
        if role == "generation":
            raise ValueError("Generation workers require the Qdrant backend")
        return "owner"
    return "generation" if role == "generation" else "writer"


def claim_kinds(role):
    from app.services.job_service import OPERATIONS

    if role == "generation":
        return sorted(GENERATION_KINDS)
    if role == "writer":
        return sorted(set(OPERATIONS) - GENERATION_KINDS)
    return sorted(OPERATIONS)
