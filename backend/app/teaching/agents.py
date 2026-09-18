"""Explicit role adapters; the model never selects or discovers arbitrary tools."""

ROLE_TOOLS = {
    "planner": frozenset({"outline_material", "validate_outline", "generate_outline"}),
    "teacher": frozenset({"load_frozen_plan", "lesson_material", "validate_lesson", "generate_lesson",
                          "preview_lesson_blocks"}),
    "reviewer": frozenset({"read_candidate", "read_frozen_sources", "validate_references", "review_candidate"}),
}


def require_role_tool(role, tool):
    if tool not in ROLE_TOOLS.get(role, frozenset()):
        raise ValueError("teaching_agent_tool_forbidden")


class PlannerAgent:
    role = "planner"

    def __init__(self, generator, policy):
        self.generator, self.policy = generator, policy

    async def __call__(self, request, *, budget):
        require_role_tool(self.role, "generate_outline")
        if request.kind != "outline":
            raise ValueError("teaching_agent_tool_forbidden")
        return await self.generator.generate_once(
            "outline", request.spec, request.material, budget=budget,
            course_criteria=list(request.course_criteria), feedback_codes=request.feedback_codes,
            findings=request.findings, generation_revision=request.generation_revision, policy=self.policy,
        )


class TeacherAgent:
    role = "teacher"

    def __init__(self, generator, policy):
        self.generator, self.policy = generator, policy

    async def __call__(self, request, *, budget):
        require_role_tool(self.role, "generate_lesson")
        # Only this role may append validated lesson blocks to the private preview.
        require_role_tool(self.role, "preview_lesson_blocks")
        if request.kind != "lesson" or request.unit is None:
            raise ValueError("teaching_agent_tool_forbidden")
        return await self.generator.generate_once(
            "lesson", request.spec, request.material, unit=request.unit, budget=budget,
            course_criteria=list(request.course_criteria), feedback_codes=request.feedback_codes,
            findings=request.findings, generation_revision=request.generation_revision, policy=self.policy,
        )


class ReviewerAgent:
    role = "reviewer"

    def __init__(self, reviewer, policy):
        self.reviewer, self.policy = reviewer, policy

    async def __call__(self, request, candidate, *, budget, policy_hash):
        from app.teaching.reviewer import TeachingReviewUnavailable

        require_role_tool(self.role, "review_candidate")
        if self.reviewer is None or not self.policy.review_enabled:
            raise TeachingReviewUnavailable("reviewer_unavailable")
        return await self.reviewer.review(request, candidate, budget=budget, policy_hash=policy_hash, policy=self.policy)
