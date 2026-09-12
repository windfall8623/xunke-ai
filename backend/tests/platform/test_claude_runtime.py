"""Native Claude SDK through real loopback HTTP, durable jobs, and isolated MySQL."""

import json

import pytest

from tests.helpers.provider_http import (
    ProviderHTTPServer,
    ProviderReply,
    anthropic_message,
)


class LearningScenario:
    def __init__(self):
        self.stages = []
        self.report_status = 200

    def __call__(self, request):
        assert request.path == "/v1/messages"
        assert request.body["model"] == "claude-local-test"
        system = request.body["system"]
        human = request.body["messages"][0]["content"]
        if isinstance(human, list):
            human = "".join(part["text"] for part in human if part["type"] == "text")
        if "学习出题器" in system:
            self.stages.append("quiz")
            data = json.loads(human)
            assert data["source_status"] == "model_only"
            assert data["question_count"] == 3
            assert data["evidence"] == []
            targets = data["coverage"]["targets"]
            assert len(targets) == 1 and targets[0]["question_quota"] == 3
            target_id = targets[0]["target_id"]
            facts = [
                (
                    "植物进行光合作用时主要利用哪种能量？",
                    "光能",
                    "声能",
                    "光合作用利用光能。",
                ),
                (
                    "叶绿体进行光合作用时会固定哪种气体？",
                    "二氧化碳",
                    "氮气",
                    "光合作用固定二氧化碳。",
                ),
                (
                    "植物通过光合作用合成的有机物属于哪一类？",
                    "糖类",
                    "岩石",
                    "光合作用产生糖类有机物。",
                ),
            ]
            payload = {
                "title": "光合作用练习",
                "summary": "本地合成协议测试题",
                "questions": [
                    {
                        "id": f"q{number}",
                        "type": "single",
                        "stem": stem,
                        "options": [
                            {"key": "A", "text": correct},
                            {"key": "B", "text": wrong},
                        ],
                        "answer": ["A"],
                        "explanation": explanation,
                        "knowledge_point": "光合作用",
                        "difficulty": "easy",
                        "citation_refs": [],
                        "support_quotes": [],
                        "coverage_target_id": target_id,
                    }
                    for number, (stem, correct, wrong, explanation) in enumerate(
                        facts, 1
                    )
                ],
            }
            tokens = (31, 17)
        elif "独立核验整套学习题" in system:
            self.stages.append("semantic")
            data = json.loads(human)
            assert data["source_status"] == "model_only"
            questions = data["quiz"]["questions"]
            assert [question["id"] for question in questions] == ["q1", "q2", "q3"]
            payload = {
                "passed": True,
                "checks": [
                    {
                        "question_id": question["id"],
                        "source_supported": False,
                        "answer_valid": True,
                        "explanation_valid": True,
                        "not_duplicate": True,
                        "false_has_counterevidence": False,
                    }
                    for question in questions
                ],
                "errors": [],
            }
            tokens = (23, 11)
        elif "学习复盘教练" in system:
            self.stages.append("report")
            assert '"correct_count": 3' in human
            assert '"xp_awarded": 16' in human
            if self.report_status != 200:
                return ProviderReply(
                    status=self.report_status,
                    body={
                        "type": "error",
                        "error": {
                            "type": "rate_limit_error",
                            "message": "Synthetic local rate limit",
                        },
                        "request_id": "req_local_report_error",
                    },
                    headers={"Retry-After": "0"},
                )
            payload = {
                "accuracy": 0,
                "xp_awarded": 999,
                "mastered_points": ["光能转换", "二氧化碳固定"],
                "weak_points": [],
                "three_line_summary": [
                    "认识光能来源。",
                    "理解二氧化碳固定。",
                    "掌握有机物合成。",
                ],
                "advice": ["继续比较光合作用与呼吸作用。"],
                "share_quote": "循序渐进地学习。",
            }
            tokens = (19, 13)
        else:
            raise AssertionError("Unexpected native learning prompt")
        return ProviderReply(
            anthropic_message(
                json.dumps(payload, ensure_ascii=False),
                input_tokens=tokens[0],
                output_tokens=tokens[1],
            )
        )


@pytest.fixture
def claude_service():
    scenario = LearningScenario()
    with ProviderHTTPServer(scenario) as server:
        yield server, scenario


@pytest.fixture
def claude_runtime_settings(platform_settings, claude_service, monkeypatch):
    # SDK transports stay real; a developer's HTTP proxy must not route loopback
    # fixture requests away from this process.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    server, _scenario = claude_service
    settings = platform_settings
    settings.llm_provider = "anthropic"
    settings.anthropic_api_key = "test-native-runtime-key"
    settings.anthropic_base_url = server.base_url + "/v1"
    settings.anthropic_model = "claude-local-test"
    settings.deepseek_api_key = ""
    settings.llm_api_key = ""
    settings.dashscope_api_key = ""
    settings.dashscope_image_api_key = ""
    settings.tavily_api_key = ""
    settings.enable_web_search = False
    settings.reranker_base_url = ""
    settings.reranker_model = ""
    settings.legacy_source_archive = ""
    settings.legacy_source_archive_sha256 = ""
    settings.rag_pipeline_id = "dense-v1"
    settings.provider_timeout_seconds = 5
    settings.job_max_attempts = 1
    settings.llm_input_cny_per_million = 2
    settings.llm_output_cny_per_million = 4
    settings.pricing_version = "synthetic-claude-runtime-v1"
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "report_status", [200, 429], ids=["report-completed", "report-rate-limited"]
)
async def test_native_claude_learning_flow_journals_calls_and_preserves_settlement(
    claude_runtime_settings, learner, claude_service, report_status
):
    from app.core.db import fetch_all, fetch_one
    from app.core.values import load
    from app.workers.providers import build_runtime
    from app.workers.rag_owner import OwnerWorker

    api, session = learner
    owner = session["user"]["id"]
    server, scenario = claude_service
    scenario.report_status = report_status
    runtime = build_runtime(claude_runtime_settings)
    try:
        worker = OwnerWorker(runtime.engine, report_generator=runtime.report_generator)
        created = await api.post(
            "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "native-claude-learning"},
            json={
                "user_input": "光合作用",
                "question_count": 3,
                "difficulty": "easy",
                "source_policy": "topic",
                "generate_images": False,
            },
        )
        assert created.status_code == 202, created.text
        quiz_task = created.json()["data"]["task_id"]
        assert await worker.run_once(task_id=quiz_task)
        result = await api.get("/api/v1/quiz/task/" + quiz_task)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["status"] == "completed", result.text
        quiz = result.json()["data"]["result"]
        assert quiz["source_status"] == "model_only"
        assert len(quiz["questions"]) == 3
        assert all(
            "answer" not in question and not question["citation_refs"]
            for question in quiz["questions"]
        )

        run = await fetch_one(
            "SELECT evidence_artifact_key FROM rag_runs WHERE owner_id=%s AND mode='production'",
            (owner,),
        )
        artifact = json.loads(
            runtime.engine.store.resolve_key(run["evidence_artifact_key"]).read_text(
                encoding="utf-8"
            )
        )
        assert artifact["validation"]["semantic_status"] == "passed"
        assert (
            artifact["validation"]["semantic_details"]["validator_model"]
            == "claude-local-test"
        )
        assert artifact["validation"]["semantic_details"]["human_ground_truth"] is False
        assert artifact["usage"]["llm_calls"] == 2
        # The admission ledger retains conservative input bounds. Observed SDK
        # usage is preserved separately in its durable per-call journal.
        assert (
            artifact["usage"]["token_count_method"]
            == "provider-reported-or-utf8-upper-bound-v1"
        )
        assert sum(call["input_tokens"] for call in artifact["usage"]["calls"]) == 54
        assert artifact["usage"]["output_tokens"] == 28
        assert artifact["usage"]["ledger_complete"] is True

        for question in quiz["questions"]:
            answer = await api.put(
                f"/api/v1/quiz/{quiz['quiz_id']}/answers/{question['id']}",
                json={"selected_answers": ["A"], "duration_ms": 120},
            )
            assert answer.status_code == 200, answer.text
        settled = await api.post(
            f"/api/v1/quiz/{quiz['quiz_id']}/complete", json={"expected_revision": 3}
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["data"]["xp_awarded"] == 16
        report_job = await fetch_one(
            "SELECT task_id FROM quiz_tasks WHERE quiz_id=%s AND kind='report'",
            (quiz["quiz_id"],),
        )
        assert await worker.run_once(task_id=report_job["task_id"])
        assert not await worker.run_once(task_id=report_job["task_id"])
        outcome = await api.get("/api/v1/report/" + quiz["quiz_id"])
        assert outcome.status_code == 200, outcome.text
        report = outcome.json()["data"]
        assert report["accuracy"] == 100 and report["xp_awarded"] == 16
        assert report["correct_count"] == 3
        if report_status == 200:
            assert report["report_status"] == "completed", outcome.text
            assert report["report"]["mastered_points"] == ["光能转换", "二氧化碳固定"]
            assert (
                "accuracy" not in report["report"]
                and "xp_awarded" not in report["report"]
            )
        else:
            assert report["report_status"] == "failed", outcome.text
            assert report["report"] is None

        repeated = await api.post(
            f"/api/v1/quiz/{quiz['quiz_id']}/complete", json={"expected_revision": 3}
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["data"]["xp_awarded"] == 16
        assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))[
            "total_xp"
        ] == 16
        assert (
            await fetch_one(
                "SELECT COUNT(*) AS n FROM answer_records WHERE user_id=%s", (owner,)
            )
        )["n"] == 1
        assert (
            await fetch_one(
                "SELECT COUNT(*) AS n FROM quiz_tasks WHERE user_id=%s AND kind='report'",
                (owner,),
            )
        )["n"] == 1

        calls = await fetch_all(
            "SELECT operation_id,stage,mode,status,usage_json FROM provider_calls WHERE owner_id=%s ORDER BY created_at,call_id",
            (owner,),
        )
        assert len(calls) == 3
        assert [call["operation_id"] for call in calls] == [
            quiz_task,
            quiz_task,
            report_job["task_id"],
        ]
        assert {(call["stage"], call["mode"]) for call in calls} == {
            ("llm", "production")
        }
        usages = [load(call["usage_json"]) for call in calls]
        for observed, (input_tokens, output_tokens, cost) in zip(
            usages[:2], [(31, 17, 0.00013), (23, 11, 0.00009)], strict=True
        ):
            assert observed["input_tokens"] == input_tokens
            assert observed["output_tokens"] == output_tokens
            assert observed["cost_cny"] == pytest.approx(cost)
            assert observed["cost_status"] == "estimated"
            assert observed["pricing_version"] == "synthetic-claude-runtime-v1"
        if report_status == 200:
            assert [call["status"] for call in calls] == ["completed"] * 3
            assert usages[2]["input_tokens"] == 19 and usages[2]["output_tokens"] == 13
            assert usages[2]["cost_cny"] == pytest.approx(0.00009)
        else:
            assert [call["status"] for call in calls] == [
                "completed",
                "completed",
                "unknown",
            ]
            assert (
                usages[2]["cost_status"] == "unknown" and usages[2]["cost_cny"] is None
            )
            reserved = await fetch_one(
                "SELECT status,reserved FROM budget_reservations WHERE operation_id=%s AND resource_type='cny'",
                (usages[2]["call_id"],),
            )
            assert reserved["status"] == "unknown" and reserved["reserved"] > 0

        assert scenario.stages == ["quiz", "semantic", "report"]
        assert len(server.requests) == 3
        assert all(
            request.headers["x-api-key"] == "test-native-runtime-key"
            for request in server.requests
        )
        assert all(request.body["max_tokens"] == 4096 for request in server.requests)
    finally:
        await runtime.close()
