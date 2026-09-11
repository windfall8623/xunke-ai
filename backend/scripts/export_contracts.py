"""Export canonical JSON schemas/OpenAPI; --check fails on any contract drift."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def outputs():
    from pydantic import TypeAdapter

    from app.main import app
    from app.learning import contracts as learning_contracts
    from app.models import sources, study
    from app.models.eval_contracts import DatasetManifest, EvalSample
    from app.models.evaluation import MetricValue
    from app.practice.contracts import GradeArtifact, PracticeArtifact, PracticeSpec
    from app.qa.contracts import ChatAnswerArtifact
    from app.rag import contracts
    from app.rag.evaluation_artifacts import (
        AnswerGradingEvalArtifact,
        EvaluationArtifact,
        PracticeGenerationEvalArtifact,
    )

    names = (
        "QuizSpec",
        "ActorContext",
        "ResolvedScope",
        "ExecutionContext",
        "DocumentEvidence",
        "WebEvidence",
        "EvidencePack",
        "QuizArtifact",
        "RetrievalArtifact",
        "PolicyArtifact",
        "PipelineManifest",
        "RunManifest",
        "BuildResult",
        "CanonicalDocument",
    )
    schemas = {
        name + ".schema.json": TypeAdapter(getattr(contracts, name)).json_schema()
        for name in names
    }
    schemas.update(
        {
            "DatasetManifest.schema.json": DatasetManifest.model_json_schema(),
            "EvalSample.schema.json": TypeAdapter(EvalSample).json_schema(),
            "MetricValue.schema.json": MetricValue.model_json_schema(),
            "ChatAnswerArtifact.schema.json": ChatAnswerArtifact.model_json_schema(),
            "EvaluationArtifact.schema.json": TypeAdapter(
                EvaluationArtifact
            ).json_schema(),
            "PracticeGenerationEvalArtifact.schema.json": PracticeGenerationEvalArtifact.model_json_schema(),
            "AnswerGradingEvalArtifact.schema.json": AnswerGradingEvalArtifact.model_json_schema(),
        }
    )
    learning_names = (
        "ObjectiveRef",
        "QuestionConceptBinding",
        "LearningAttemptDraft",
        "AttemptRef",
        "AssessmentDraft",
        "AssessmentRef",
        "LearningCompletionRef",
        "QaPracticeContext",
        "ConceptState",
        "LearningOutcome",
        "ReviewDecision",
    )
    schemas.update(
        {
            name + ".schema.json": TypeAdapter(
                getattr(learning_contracts, name)
            ).json_schema(mode="serialization")
            for name in learning_names
        }
    )
    schemas.update(
        {
            "PracticeArtifact.schema.json": PracticeArtifact.model_json_schema(
                mode="serialization"
            ),
            "GradeArtifact.schema.json": GradeArtifact.model_json_schema(
                mode="serialization"
            ),
            "PracticeSpec.schema.json": PracticeSpec.model_json_schema(
                mode="serialization"
            ),
        }
    )
    public_names = (
        "StudySpaceCreate",
        "StudySpaceUpdate",
        "StudyScopeUpdate",
        "StudyScopeView",
        "StudySpaceView",
        "StudySpaceList",
        "StudyGoalCreate",
        "StudyGoalUpdate",
        "StudyGoalView",
        "StudyGoalList",
        "StudyUnitCreate",
        "StudyUnitUpdate",
        "StudyUnitReorder",
        "StudyUnitView",
        "StudyUnitList",
        "StudyConceptCreate",
        "StudyConceptUpdate",
        "StudyConceptView",
        "StudyConceptList",
        "StudyQaPracticeContextView",
        "StudyQuizFromQaBody",
        "ReviewQuizBody",
        "ReviewUpdateBody",
    )
    schemas.update(
        {
            name + ".schema.json": TypeAdapter(getattr(study, name)).json_schema()
            for name in public_names
        }
    )
    schemas.update(
        {
            name + ".schema.json": TypeAdapter(getattr(study, name)).json_schema(
                mode="serialization"
            )
            for name in (
                "StudyReviewView",
                "StudyReviewList",
                "StudyWrongQuestionView",
                "StudyWrongQuestionList",
                "StudyHistoryView",
                "StudyHistoryList",
                "StudyConceptStateView",
                "StudyConceptProgressView",
            )
        }
    )
    schemas.update(
        {
            name + ".schema.json": TypeAdapter(getattr(sources, name)).json_schema()
            for name in ("PublicSourceManifest", "PublicResolvedScope")
        }
    )
    # Dataset/result APIs retain their compatible JSON transport. Publish the
    # canonical discriminated contracts as components so web clients use the
    # same private question/grade types instead of maintaining a second schema.
    openapi = app.openapi()
    components = openapi.setdefault("components", {}).setdefault("schemas", {})

    def openapi_refs(value):
        if isinstance(value, dict):
            return {key: openapi_refs(item) for key, item in value.items()}
        if isinstance(value, list):
            return [openapi_refs(item) for item in value]
        if isinstance(value, str) and value.startswith("#/$defs/"):
            return value.replace("#/$defs/", "#/components/schemas/", 1)
        return value

    for contract in (
        "EvalSample",
        "EvaluationArtifact",
        "PracticeGenerationEvalArtifact",
        "AnswerGradingEvalArtifact",
    ):
        definition = dict(schemas[contract + ".schema.json"])
        for name, item in definition.pop("$defs", {}).items():
            components.setdefault(name, openapi_refs(item))
        components[contract] = openapi_refs(definition)
    schemas["openapi.json"] = openapi
    encoded = {
        key: json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        for key, value in schemas.items()
    }
    encoded["manifest.json"] = (
        json.dumps(
            {
                "schema_version": "1",
                "files": {
                    key: hashlib.sha256(value.encode()).hexdigest()
                    for key, value in encoded.items()
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    return encoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=BACKEND.parent / "contracts")
    args = parser.parse_args()
    changed = []
    for name, content in outputs().items():
        target = args.output / name
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                changed.append(name)
        else:
            args.output.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
    if changed:
        raise SystemExit("Contracts need regeneration: " + ", ".join(changed))
    print("Contracts match." if args.check else "Contracts exported.")


if __name__ == "__main__":
    main()
