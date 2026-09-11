"""Domain failures with stable public codes; private source text is never included."""


class RagError(Exception):
    code = "GENERATION_VALIDATION_FAILED"
    status_code = 422

    def __init__(self, message: str | None = None, *, details: dict | None = None):
        self.message = message or self.code
        self.details = details or {}
        super().__init__(self.message)


class InvalidScope(RagError):
    code = "INVALID_SCOPE"


class SourceUnavailable(RagError):
    code = "SOURCE_UNAVAILABLE"
    status_code = 409


class ScopeRevoked(SourceUnavailable):
    status_code = 404


class InsufficientEvidence(RagError):
    code = "INSUFFICIENT_EVIDENCE"


class RetrievalUnavailable(RagError):
    code = "RETRIEVAL_UNAVAILABLE"
    status_code = 503


class RerankerTimeout(RetrievalUnavailable):
    code = "RERANKER_TIMEOUT"


class ProviderTimeout(RagError):
    code = "PROVIDER_TIMEOUT"
    status_code = 504


class ProviderRateLimited(RagError):
    code = "PROVIDER_RATE_LIMITED"
    status_code = 503


class GenerationValidationFailed(RagError):
    code = "GENERATION_VALIDATION_FAILED"


class BudgetExceeded(RagError):
    code = "BUDGET_EXCEEDED"
    status_code = 429


class OwnerRequired(RetrievalUnavailable):
    """A persistent Chroma directory already has an owner, or this is not one."""
