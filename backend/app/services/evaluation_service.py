"""Evaluation orchestration shares artifacts, never learning side effects."""

import asyncio
import copy
import csv
import io
import json
from collections import Counter
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pymysql.err import IntegrityError
from rag_eval.comparison import (
    COST_PROTOCOL,
    DEFAULT_PROTOCOL,
    assess_run,
    compare_runs,
    default_protocol,
)
from rag_eval.contracts import canonical_hash, metric_config
from rag_eval.judges.config import validate_judge_config
from rag_eval.metrics import score_sample
from rag_eval.quiz_rubric import REQUIRED_SEMANTICS

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, now, uid
from app.rag.contracts import BuildResult, RerankerConfig, ResolvedScope
from app.rag.registry import get_pipeline_config
from app.services import eval_dataset_service as datasets
from app.services import job_service
from app.services.evaluation_observations import scoring_observations, scoring_store
from app.services.source_service import reauthorize_scope

NAMES = {
    "dense-v1": "向量检索基线",
    "legacy-summary-b0": "B0 历史摘要与截断快照",
    "legacy-dense-v1": "旧检索适配对照",
    "llamaindex-dense-v1": "LlamaIndex 向量检索",
    "bm25-v1": "中文词法检索",
    "hybrid-v1": "混合检索与 RRF",
    "structure-v1": "结构分块与覆盖",
    "hybrid-rerank-v1": "混合检索与重排",
    "hybrid-llm-rerank-v1": "混合检索与 LLM 重排",
    "ablation-char-v1": "消融：字符分块基线",
    "ablation-structure-v1": "消融：结构子块",
    "ablation-parent-v1": "消融：结构子块与父段",
    "ablation-coverage-v1": "消融：结构子块、父段与覆盖规划",
}


def pipeline_config(pipeline_id):
    if pipeline_id not in NAMES:
        raise AppError(422, "unknown_pipeline", "请选择已注册的检索方案")
    from app.llm.configuration import resolve_llm_config

    options = {"generator_model": resolve_llm_config(get_settings()).model}
    if pipeline_id == "legacy-summary-b0":
        import tarfile

        from app.rag.errors import RagError
        from app.rag.providers.legacy_baseline import LegacyBaselineAdapter

        s = get_settings()
        if not s.legacy_source_archive or not s.legacy_source_archive_sha256:
            raise conflict(
                "legacy_baseline_not_configured", "请先配置经校验的 B0 原始代码快照"
            )
        try:
            LegacyBaselineAdapter(
                source_archive=s.legacy_source_archive,
                archive_sha256=s.legacy_source_archive_sha256,
                source_commit=s.legacy_source_commit,
                llm=None,
                retriever=None,
                reauthorize=None,
            )
        except (OSError, ValueError, RagError, tarfile.TarError):
            raise conflict(
                "legacy_baseline_invalid", "B0 原始代码快照校验未通过"
            ) from None
        options.update(
            legacy_source_archive_sha256=s.legacy_source_archive_sha256,
            legacy_source_commit=s.legacy_source_commit,
        )
    if pipeline_id == "hybrid-rerank-v1":
        s = get_settings()
        if (
            not s.reranker_base_url
            or not s.reranker_model
            or not getattr(s, "reranker_model_revision", "")
        ):
            raise conflict("reranker_not_configured", "重排服务尚未配置并固定模型版本")
        options["reranker"] = RerankerConfig(
            provider=s.reranker_model,
            model_revision=s.reranker_model_revision,
            license=s.reranker_license,
            endpoint=s.reranker_base_url,
        )
    if pipeline_id == "hybrid-llm-rerank-v1":
        from app.rag.providers.llm_reranker_config import llm_reranker_config

        try:
            options["reranker"] = llm_reranker_config(get_settings())
        except ValueError:
            raise conflict(
                "reranker_not_configured", "请先配置当前生成模型以启用 LLM 重排"
            ) from None
    return get_pipeline_config(
        "llamaindex-dense-v1" if pipeline_id == "dense-v1" else pipeline_id, **options
    )


def list_pipelines():
    items = []
    for identifier, name in NAMES.items():
        try:
            config = pipeline_config(identifier)
        except AppError:
            continue
        items.append(
            {
                "pipeline_id": identifier,
                "name": name,
                "description": "固定参数；真实收益以配对评测为准",
                "index_profile_id": config.index_profile_id,
                "config": config.model_dump(mode="json"),
            }
        )
    return {"items": items, "total": len(items)}


def code_fingerprint():
    root = Path(__file__).resolve().parents[1]
    return digest(
        "".join(
            p.relative_to(root).as_posix() + digest(p.read_bytes())
            for p in sorted(root.rglob("*.py"))
        )
    )


def judge_calibrated_for_samples(samples, scorer):
    # The registered external judge only supports quiz rubrics. QA production
    # validation and a general thumbs-up review do not calibrate an eval judge.
    if any(
        sample["case_type"] in {"qa", "practice_generation", "answer_grading"}
        for sample in samples
    ):
        return False
    return (
        not any(sample["case_type"] == "quiz" for sample in samples)
        or scorer.get("external_judge", {}).get("calibrated") is True
    )


def scoring_config(profile_id):
    base = {"metric_version": "evidence-v1", "semantic_judge": "disabled"}
    if profile_id == "deterministic-v1":
        return base
    if profile_id != "ragas-faithfulness-v1":
        raise AppError(422, "unknown_judge_profile", "请选择已注册的评分方案")
    configured = get_settings().eval_judge_config_path
    try:
        if not configured:
            raise ValueError()
        path = Path(configured)
        if path.stat().st_size > 65536:
            raise ValueError()
        config = validate_judge_config(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, TypeError):
        raise conflict(
            "judge_not_configured", "管理员尚未完成固定模型、提示词、费用与评分服务配置"
        ) from None
    return {**base, "external_judge": config}


def list_judges():
    items = [
        {
            "judge_profile_id": "deterministic-v1",
            "name": "确定性指标与人工复核",
            "description": "检查证据、结构、检索和成本；语义质量保留待人工复核",
            "calibrated": False,
        }
    ]
    try:
        config = scoring_config("ragas-faithfulness-v1")["external_judge"]
    except AppError:
        pass
    else:
        items.append(
            {
                "judge_profile_id": "ragas-faithfulness-v1",
                "name": "Ragas 忠实度辅助评分",
                "description": "调用已配置模型评估来源支持性，并保留人工题目质量复核",
                "calibrated": config["calibrated"],
            }
        )
    return {"items": items, "total": len(items)}


def runtime_dependencies():
    backend = Path(__file__).resolve().parents[2]
    paths = {
        "backend": [backend / "requirements.lock"],
        "evaluation": [
            backend.parent / "evaluation" / "requirements.lock",
            backend / "evaluation-runtime" / "requirements.lock",
        ],
        "evaluation_ragas": [
            backend.parent / "evaluation" / "requirements-ragas.lock",
            backend / "evaluation-runtime" / "requirements-ragas.lock",
        ],
    }
    result = {}
    for name, choices in paths.items():
        path = next((candidate for candidate in choices if candidate.is_file()), None)
        result[name] = {
            "sha256": digest(path.read_bytes()) if path else None,
            "status": "recorded" if path else "unavailable",
        }
    return result


def provider_manifest():
    from app.llm.configuration import resolve_llm_config

    s = get_settings()
    generator = resolve_llm_config(s)
    return {
        "generator_provider": generator.provider,
        "generator_model": generator.model,
        "generator_endpoint_hash": digest(generator.base_url),
        "embedding_model": s.dashscope_embedding_model,
        "embedding_endpoint_hash": digest(s.dashscope_base_url),
        "embedding_dimensions": s.embedding_dimensions,
        "pricing": {
            field: getattr(s, field)
            for field in (
                "pricing_version",
                "pricing_usd_to_cny",
                "llm_input_cny_per_million",
                "llm_output_cny_per_million",
                "llm_cache_read_cny_per_million",
                "llm_cache_write_cny_per_million",
                "embedding_cny_per_million",
                "rerank_call_cny",
                "search_call_cny",
                "image_call_cny",
            )
        },
    }


def require_provider_configuration(manifest):
    """A frozen run must not silently execute with another provider or price."""
    frozen = manifest.get("provider_config")
    current = provider_manifest()
    expected = copy.deepcopy(frozen) if isinstance(frozen, dict) else None
    if expected is not None:
        if "generator_provider" not in expected:
            # Legacy manifests hashed the raw DeepSeek URL, including its slash.
            expected["generator_provider"] = "deepseek"
            if current["generator_provider"] == "deepseek":
                current["generator_endpoint_hash"] = digest(
                    get_settings().deepseek_base_url
                )
        prices = expected.get("pricing")
        if isinstance(prices, dict):
            # Missing cache prices in an older manifest mean unknown, not zero.
            for field in (
                "pricing_usd_to_cny",
                "llm_cache_read_cny_per_million",
                "llm_cache_write_cny_per_million",
            ):
                prices.setdefault(field, None)
    if expected != current:
        raise conflict(
            "provider_configuration_changed",
            "当前模型服务或计价配置与冻结评测不一致，请恢复原配置或创建新运行",
        )


async def sample_scope(owner, sample, cache, config):
    manifests = []
    for ref in sample.get("source_refs", []):
        key = (
            ref["doc_id"],
            ref.get("source_version_id", ref.get("document_version_id")),
            ref["parse_artifact_id"],
        )
        _canonical, build, auth_revision = cache[key]
        if build.profile.profile_id != config.index_profile_id:
            compatible = await fetch_one(
                "SELECT manifest_json FROM kb_index_builds WHERE owner_id=%s AND doc_id=%s AND version_id=%s AND parse_artifact_id=%s AND index_profile_id=%s AND status='ready' ORDER BY created_at DESC LIMIT 1",
                (owner, *key, config.index_profile_id),
            )
            if not compatible:
                raise conflict(
                    "index_profile_mismatch", "评测资料缺少该方案的索引，请先重建"
                )
            build = BuildResult.model_validate(load(compatible["manifest_json"]))
        manifests.append(
            build.to_source_manifest(auth_revision, ref.get("section_ids", []))
        )
    # Sources may repeat in the manifest; selected documents may not.
    manifests = list({m.doc_id: m for m in manifests}.values())
    scope = ResolvedScope(
        owner_id=owner, namespace=f"evaluation:{owner}", documents=manifests
    )
    await reauthorize_scope(scope)
    return scope


async def authorized_run(owner, run_id, *, allow_revoked_metadata=False, conn=None):
    row = await fetch_one(
        "SELECT * FROM eval_runs WHERE run_id=%s AND owner_id=%s",
        (run_id, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    dataset = await datasets.dataset_row(
        owner, row["dataset_id"], row["dataset_version"], conn=conn
    )
    if dataset["status"] == "revoked":
        if allow_revoked_metadata:
            return row
        raise not_found()
    await datasets.hydrate(
        owner, load(dataset["manifest_json"]), load(dataset["samples_json"]), conn=conn
    )
    return row


def require_reproducible(row):
    manifest = load(row["manifest_json"])
    if (
        manifest.get("raw_artifacts_status") == "expired"
        or manifest.get("reproducible") is False
    ):
        raise conflict(
            "raw_artifacts_expired",
            "原始评测工件已按保留策略清理，可查看历史指标，不能继续评分或正式比较",
        )


async def locked_run(owner, run_id, conn):
    preview = await authorized_run(owner, run_id, conn=conn)
    dataset = await datasets.dataset_row(
        owner, preview["dataset_id"], preview["dataset_version"], conn=conn, lock=True
    )
    if (
        dataset["status"] != "frozen"
        or digest(
            dump(
                {
                    "manifest": load(dataset["manifest_json"]),
                    "samples": load(dataset["samples_json"]),
                }
            )
        )
        != dataset["checksum"]
    ):
        raise conflict("dataset_changed", "评测数据集已撤销或校验不一致")
    row = await fetch_one(
        "SELECT * FROM eval_runs WHERE run_id=%s AND owner_id=%s FOR UPDATE",
        (run_id, owner),
        conn=conn,
    )
    require_reproducible(row)
    return row


async def create_run(actor, body, key):
    if not key or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    request_hash = digest(dump(body.model_dump()))
    max_cost_cny = float(
        Decimal(str(body.max_cost_cny)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
    )
    old = await fetch_one(
        "SELECT run_id,request_hash FROM eval_runs WHERE owner_id=%s AND idempotency_key=%s",
        (actor.owner_id, key),
    )
    if old:
        if old["request_hash"] != request_hash:
            raise conflict("idempotency_conflict", "相同操作标识已用于不同评测请求")
        return await get_run(actor.owner_id, old["run_id"])
    config = pipeline_config(body.pipeline_id)
    scorer = scoring_config(body.judge_profile_id)
    dataset = await datasets.dataset_row(
        actor.owner_id, body.dataset_id, body.dataset_version
    )
    if dataset["status"] != "frozen":
        raise conflict("dataset_not_frozen", "请先完成人工复核并冻结数据集")
    manifest = load(dataset["manifest_json"])
    samples = load(dataset["samples_json"])
    case_types = {sample["case_type"] for sample in samples}
    learning_cases = case_types & {"practice_generation", "answer_grading"}
    case_configs = {}
    if learning_cases:
        if config.pipeline_version == "legacy-summary-b0":
            raise AppError(
                422, "unsupported_evaluation_pipeline", "历史出题快照不支持新题型评测"
            )
        scorer = metric_config(
            {name: value for name, value in scorer.items() if name != "metric_version"},
            case_types,
        )
        if "practice_generation" in learning_cases:
            from app.prompts.practice_prompt import PROMPT_VERSION

            practice_config = config.model_copy(
                update={
                    "prompt_version": PROMPT_VERSION,
                    "require_semantic_validation": True,
                    "max_retrieval_rounds": 1,
                }
            )
            case_configs["practice_generation"] = {
                "config": practice_config.model_dump(mode="json"),
                "hash": practice_config.pipeline_config_hash,
            }
    if digest(dump({"manifest": manifest, "samples": samples})) != dataset["checksum"]:
        raise conflict("dataset_checksum_mismatch", "数据集校验和不一致")
    validation, cache = await datasets.validated(
        actor.owner_id, manifest, samples, frozen=True
    )
    scopes = {
        s["sample_id"]: await sample_scope(actor.owner_id, s, cache, config)
        for s in samples
    }
    run_id = uid("eval")
    deadline = now() + timedelta(hours=6)
    run_manifest = {
        "schema_version": "1",
        "dataset_hash": dataset["checksum"],
        "annotation_version": manifest.get("annotation_version", "v1"),
        "metric_version": scorer["metric_version"],
        "judge_profile_id": body.judge_profile_id,
        "judge_config_hash": digest(dump(scorer))
        if "external_judge" in scorer
        else "deterministic-v1",
        "cache_protocol": "cold",
        "context_token_budget": config.context_token_budget,
        "split": next(iter({s["split"] for s in samples}))
        if len({s["split"] for s in samples}) == 1
        else "mixed",
        "repeat_count": body.repeat_count,
        "dataset_state": "frozen",
        "sample_clusters": {
            sid: cluster
            for cluster, ids in validation["clusters"].items()
            for sid in ids
        },
        "gold_reviewed": validation["review"]["human_reviewed_count"] == len(samples),
        "release_gold_status": validation["release_gold_status"],
        "formal_gold_eligible": validation["formal_gold_eligible"],
        "judge_calibrated": judge_calibrated_for_samples(samples, scorer),
        "protocol_frozen": True,
        "planned_sample_ids": [s["sample_id"] for s in samples],
        "pipeline_config": config.model_dump(mode="json"),
        "pipeline_config_hash": config.pipeline_config_hash,
        "code_hash": code_fingerprint(),
        "runtime_dependencies": runtime_dependencies(),
        "provider_config": provider_manifest(),
        "source_scopes": {
            key: scope.model_dump(mode="json") for key, scope in scopes.items()
        },
        "scoring_config": scorer,
        "retry_policy": {
            "prediction_max_attempts": 2,
            "scoring_max_attempts": 2,
            "select_best": False,
        },
        "cost_estimate": {
            "kind": "conservative_ceiling",
            "max_cost_cny": max_cost_cny,
            "not_a_bill": True,
        },
        "cost_protocol": {**COST_PROTOCOL, "max_cost_cny": max_cost_cny},
    }
    if learning_cases:
        protocol = default_protocol(case_types)
        protocol["grading_accept_threshold"] = scorer["grading_accept_threshold"]
        run_manifest.update(
            comparison_protocol=protocol,
            protocol_version=protocol["protocol_version"],
            case_pipeline_configs=case_configs,
            grading_auto_confirmation=False,
        )
    async with transaction() as conn:
        for scope in scopes.values():
            await reauthorize_scope(scope, conn=conn)
        locked = await datasets.dataset_row(
            actor.owner_id, body.dataset_id, body.dataset_version, conn=conn, lock=True
        )
        if locked["status"] != "frozen" or locked["checksum"] != dataset["checksum"]:
            raise conflict("dataset_changed", "数据集状态已发生变化")
        repeated = await fetch_one(
            "SELECT run_id,request_hash FROM eval_runs WHERE owner_id=%s AND idempotency_key=%s",
            (actor.owner_id, key),
            conn=conn,
        )
        if repeated:
            if repeated["request_hash"] != request_hash:
                raise conflict("idempotency_conflict", "相同操作标识已用于不同评测请求")
            run_id = repeated["run_id"]
        else:
            # Recheck frozen version under lock immediately before scheduling.
            locked = await datasets.dataset_row(
                actor.owner_id,
                body.dataset_id,
                body.dataset_version,
                conn=conn,
                lock=True,
            )
            if (
                locked["status"] != "frozen"
                or locked["checksum"] != dataset["checksum"]
            ):
                raise conflict("dataset_changed", "数据集状态已发生变化")
            try:
                await execute(
                    "INSERT INTO eval_runs(run_id,owner_id,dataset_id,dataset_version,pipeline_id,manifest_json,request_hash,idempotency_key,repeat_count,max_cost_cny,deadline_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        run_id,
                        actor.owner_id,
                        body.dataset_id,
                        body.dataset_version,
                        body.pipeline_id,
                        dump(run_manifest),
                        request_hash,
                        key,
                        body.repeat_count,
                        max_cost_cny,
                        deadline,
                    ),
                    conn=conn,
                )
            except IntegrityError as exc:
                if exc.args[0] == 1062:
                    raise conflict(
                        "idempotency_conflict", "相同操作标识已用于不同评测请求"
                    ) from None
                raise
            await execute(
                "INSERT INTO budget_accounts(account_key,resource_type,quota) VALUES(%s,%s,%s)",
                (f"eval_run:{run_id}:cny", "cny", max_cost_cny),
                conn=conn,
            )
            for sample in samples:
                for repeat in range(body.repeat_count):
                    result_id = uid("result")
                    await execute(
                        "INSERT INTO eval_results(result_id,run_id,sample_id,repeat_index,case_type,sample_json) VALUES(%s,%s,%s,%s,%s,%s)",
                        (
                            result_id,
                            run_id,
                            sample["sample_id"],
                            repeat,
                            sample["case_type"],
                            dump(sample),
                        ),
                        conn=conn,
                    )
                    job = await job_service.enqueue_job(
                        actor.owner_id,
                        "eval_sample",
                        {
                            "run_id": run_id,
                            "result_id": result_id,
                            **(
                                {
                                    "grading_request_id": "evalgrade_"
                                    + digest(dump([run_id, result_id]))[:40],
                                }
                                if sample["case_type"] == "answer_grading"
                                else {}
                            ),
                            **(
                                {
                                    "generation_request_id": "evalgen_"
                                    + digest(dump([run_id, result_id]))[:40],
                                }
                                if sample["case_type"] == "practice_generation"
                                else {}
                            ),
                        },
                        f"eval:{result_id}",
                        scope=scopes[sample["sample_id"]].model_dump(mode="json"),
                        mode="evaluation",
                        conn=conn,
                    )
                    await execute(
                        "UPDATE quiz_tasks SET queued_expires_at=%s WHERE task_id=%s",
                        (deadline, job["task_id"]),
                        conn=conn,
                    )
    return await get_run(actor.owner_id, run_id)


async def get_run(owner, run_id):
    row = await authorized_run(owner, run_id, allow_revoked_metadata=True)
    rows = await fetch_all(
        "SELECT sample_id,repeat_index,case_type,status,prediction_status,sample_json,metrics_json,review_json FROM eval_results WHERE run_id=%s",
        (run_id,),
    )
    counts = Counter(r["status"] for r in rows)
    total = sum(counts.values())
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    status = row["status"]
    if status not in ("failed", "cancelled"):
        if completed + failed == total:
            status = "completed"
        elif (
            counts.get("pending_scoring", 0) + counts.get("scoring", 0) > 0
            and not counts.get("queued", 0)
            and not counts.get("running", 0)
        ):
            status = "scoring"
        elif any(k != "queued" for k in counts):
            status = "running"
        if status != row["status"]:
            await execute(
                "UPDATE eval_runs SET status=%s WHERE run_id=%s AND status NOT IN (%s,%s)",
                (status, run_id, "failed", "cancelled"),
            )
    manifest = load(row["manifest_json"])
    records = []
    human_complete = True
    for result in rows:
        sample = load(result["sample_json"])
        metrics = load(result["metrics_json"], {})
        records.append(
            {
                **{
                    k: result[k]
                    for k in ("sample_id", "repeat_index", "case_type", "status")
                },
                "family_ids": sample.get("family_ids", []),
                "split": sample.get("split"),
                "metrics": metrics,
            }
        )
        if result["case_type"] in {"qa", "answer_grading"}:
            human_complete = False
        if result["case_type"] in {"quiz", "practice_generation"}:
            reviews = load(result["review_json"], {}).get("question_reviews", [])
            generated = metrics.get("generated_question_count", {}).get("value")
            human_complete = (
                human_complete
                and bool(reviews)
                and len(reviews) == generated
                and all(
                    review.get("provenance") == "human"
                    and review.get("reviewer_id")
                    and review.get("question_hash")
                    and all(
                        type(review.get("decisions", {}).get(name)) is bool
                        for name in REQUIRED_SEMANTICS
                    )
                    for review in reviews
                )
            )
    manifest["human_adjudication_complete"] = bool(human_complete and rows)
    eligibility = assess_run(
        {
            "status": status,
            "stop_reason": row["stop_reason"],
            "manifest": manifest,
            "results": records,
            "max_cost_cny": float(row["max_cost_cny"]),
        }
    )
    account = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s",
        (f"eval_run:{run_id}:cny",),
    )
    return {
        "run_id": run_id,
        "dataset_id": row["dataset_id"],
        "dataset_version": row["dataset_version"],
        "pipeline_id": row["pipeline_id"],
        "status": status,
        "stop_reason": row["stop_reason"],
        "progress": {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": counts.get("queued", 0) + counts.get("running", 0),
            "scoring": counts.get("pending_scoring", 0) + counts.get("scoring", 0),
            "prediction_failed": sum(
                r["prediction_status"] in ("failed", "timeout", "cancelled")
                for r in rows
            ),
        },
        "comparison_eligible": eligibility["comparison_eligible"],
        "ineligibility_reasons": eligibility["ineligibility_reasons"],
        "manifest": {k: v for k, v in manifest.items() if k != "source_scopes"},
        "max_cost_cny": float(row["max_cost_cny"]),
        "spent_cny": float(account["used"]) if account else 0,
        "reserved_cny": float(account["reserved"]) if account else 0,
        "created_at": iso(row["created_at"]),
    }


async def list_runs(owner):
    rows = await fetch_all(
        "SELECT run_id FROM eval_runs WHERE owner_id=%s ORDER BY created_at DESC LIMIT 100",
        (owner,),
    )
    return {
        "items": [await get_run(owner, r["run_id"]) for r in rows],
        "total": len(rows),
    }


async def get_results(owner, run_id):
    await authorized_run(owner, run_id)
    rows = await fetch_all(
        "SELECT * FROM eval_results WHERE run_id=%s ORDER BY sample_id,repeat_index",
        (run_id,),
    )
    return {
        "items": [
            {
                **{
                    k: r[k]
                    for k in (
                        "result_id",
                        "sample_id",
                        "repeat_index",
                        "case_type",
                        "status",
                        "review_revision",
                        "error_code",
                    )
                },
                "sample": load(r["sample_json"]),
                "artifact": load(r["artifact_json"]),
                "metrics": load(r["metrics_json"]),
                "review": load(r["review_json"]),
            }
            for r in rows
        ],
        "total": len(rows),
    }


async def cancel_run(owner, run_id, reason="user_cancelled"):
    await authorized_run(owner, run_id)
    async with transaction() as conn:
        await locked_run(owner, run_id, conn)
        await execute(
            "UPDATE eval_runs SET status='cancelled',stop_reason=%s WHERE run_id=%s AND owner_id=%s AND status<>'completed'",
            (reason, run_id, owner),
            conn=conn,
        )
        await execute(
            "UPDATE eval_results SET status='cancelled',scoring_lease_token=NULL WHERE run_id=%s AND status NOT IN ('completed','failed')",
            (run_id,),
            conn=conn,
        )
    # Make the stop visible before taking business job locks. An owner publishing
    # job -> source -> dataset -> run can now observe cancellation and release.
    jobs = await fetch_all(
        "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='eval_sample' AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s AND status IN ('pending','running')",
        (owner, run_id),
    )
    for job in jobs:
        await job_service.cancel_job(owner, job["task_id"])
    return await get_run(owner, run_id)


async def resume_run(owner, run_id):
    row = await authorized_run(owner, run_id)
    require_reproducible(row)
    if row["status"] not in ("failed", "cancelled"):
        return await get_run(owner, run_id)
    async with transaction() as conn:
        # The owner publishes job -> source -> dataset -> run -> result. Resume
        # follows that order and rechecks mutable stop/budget state under lock.
        jobs = await fetch_all(
            "SELECT task_id,attempt,max_attempts,request_json,deadline_at FROM quiz_tasks WHERE user_id=%s AND kind='eval_sample' AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s AND status IN ('cancelled','failed') ORDER BY task_id FOR UPDATE",
            (owner, run_id),
            conn=conn,
        )
        current = await locked_run(owner, run_id, conn)
        if current["deadline_at"] <= now() or current["stop_reason"] not in (
            None,
            "user_cancelled",
            "worker_unavailable",
        ):
            raise conflict(
                "run_not_resumable", "原运行期限或预算不允许恢复，请创建新实验"
            )
        if current["status"] in ("failed", "cancelled"):
            for job in jobs:
                result_id = load(job["request_json"])["result_id"]
                result = await fetch_one(
                    "SELECT artifact_json,status FROM eval_results WHERE result_id=%s FOR UPDATE",
                    (result_id,),
                    conn=conn,
                )
                if (
                    result
                    and result["artifact_json"] is None
                    and result["status"] in ("failed", "cancelled", "queued")
                    and job["attempt"] < job["max_attempts"]
                    and (job["deadline_at"] is None or job["deadline_at"] > now())
                ):
                    await execute(
                        "UPDATE quiz_tasks SET status='pending',cancel_requested=FALSE,error_code=NULL WHERE task_id=%s",
                        (job["task_id"],),
                        conn=conn,
                    )
                    await execute(
                        "UPDATE eval_results SET status='queued',prediction_status='queued',error_code=NULL WHERE result_id=%s",
                        (result_id,),
                        conn=conn,
                    )
            await execute(
                "UPDATE eval_results SET status='pending_scoring',scoring_lease_token=NULL,scoring_expires_at=NULL,error_code=NULL WHERE run_id=%s AND status='cancelled' AND artifact_json IS NOT NULL AND scoring_attempt<2",
                (run_id,),
                conn=conn,
            )
            pending = await fetch_one(
                "SELECT COUNT(*) AS n FROM eval_results WHERE run_id=%s AND status IN ('queued','running','pending_scoring','scoring')",
                (run_id,),
                conn=conn,
            )
            if not pending["n"]:
                raise conflict("attempts_exhausted", "原运行已没有允许恢复的尝试")
            await execute(
                "UPDATE eval_runs SET status='running',stop_reason=NULL WHERE run_id=%s",
                (run_id,),
                conn=conn,
            )
    return await get_run(owner, run_id)


async def review_result(actor, run_id, result_id, body):
    async with transaction() as conn:
        run = await locked_run(actor.owner_id, run_id, conn)
        row = await fetch_one(
            "SELECT * FROM eval_results WHERE result_id=%s AND run_id=%s FOR UPDATE",
            (result_id, run_id),
            conn=conn,
        )
        if not row:
            raise not_found()
        if row["review_revision"] != body.expected_revision:
            raise conflict()
        if row["status"] not in ("completed", "failed") or not row["artifact_json"]:
            raise conflict("scoring_in_progress", "请等待该样本执行和评分结束后复核")
        artifact = load(row["artifact_json"])
        sample = load(row["sample_json"])
        private = artifact.get("practice") or artifact
        questions = {
            q.get("id", q.get("question_id")): q for q in private.get("questions", [])
        }
        ids = [q.question_id for q in body.question_reviews]
        if len(ids) != len(set(ids)) or any(
            identifier not in questions for identifier in ids
        ):
            raise AppError(
                422, "invalid_review_question", "复核题目必须来自本次实际输出且不可重复"
            )
        previous = load(row["review_json"], {})
        decisions = {
            item["question_id"]: item for item in previous.get("question_reviews", [])
        }
        for item in body.question_reviews:
            decisions[item.question_id] = {
                **item.model_dump(),
                "question_hash": canonical_hash(questions[item.question_id]),
                "status": "ok",
                "provenance": "human",
                "reviewer_id": str(actor.owner_id),
                "reviewed_at": iso(now()),
            }
        review = {
            "verdict": body.verdict,
            "comment": body.comment,
            "reviewer_id": actor.owner_id,
            "reviewed_at": iso(now()),
            "provenance": "human",
            "question_reviews": list(decisions.values()),
            "automatic_metrics": previous.get(
                "automatic_metrics", load(row["metrics_json"], {})
            ),
            "previous_reviews": [
                *previous.get("previous_reviews", []),
                *(
                    [
                        {
                            k: v
                            for k, v in previous.items()
                            if k not in ("previous_reviews", "automatic_metrics")
                        }
                    ]
                    if previous
                    else []
                ),
            ],
        }
        dataset = await datasets.dataset_row(
            actor.owner_id, run["dataset_id"], run["dataset_version"], conn=conn
        )
        # Source-share locks were obtained by locked_run before the result lock.
        _, hydrated, _ = await datasets.hydrate(
            actor.owner_id, load(dataset["manifest_json"]), [sample], conn=conn
        )
        usage_artifact = copy.deepcopy(artifact)
        journal = await fetch_all(
            "SELECT usage_json FROM provider_calls WHERE owner_id=%s AND mode='evaluation' AND stage='judge' AND operation_id LIKE %s",
            (actor.owner_id, f"evalscore:{result_id}:%"),
            conn=conn,
        )
        usage = usage_artifact.setdefault("usage", {})
        usage["calls"] = [
            *usage.get("calls", []),
            *[
                {
                    k: v
                    for k, v in load(call["usage_json"]).items()
                    if k not in ("events", "lease_fingerprint")
                }
                for call in journal
            ],
        ]
        run_manifest = load(run["manifest_json"])
        config = scoring_observations(
            hydrated[0],
            artifact,
            run_manifest.get("scoring_config", {}),
            run_manifest.get("source_scopes", {}).get(sample["sample_id"]),
            store=await scoring_store(
                hydrated[0],
                artifact,
                run_manifest.get("source_scopes", {}).get(sample["sample_id"]),
                conn=conn,
            ),
            reviews=decisions.values(),
        )
        metrics = score_sample(hydrated[0], usage_artifact, config)
        metrics.update(
            {
                k: v
                for k, v in load(row["metrics_json"], {}).items()
                if k.startswith("ragas_")
            }
        )
        await execute(
            "UPDATE eval_results SET review_json=%s,review_revision=review_revision+1,metrics_json=%s,status='completed' WHERE result_id=%s",
            (dump(review), dump(metrics), result_id),
            conn=conn,
        )
    return {
        "result_id": result_id,
        "review": review,
        "review_revision": body.expected_revision + 1,
    }


def group_matches(sample, group):
    tags = set(sample.get("tags", []))
    return (
        group == "all"
        or group == "pdf"
        and ("pdf" in tags or sample.get("document_type") == "pdf")
        or group == "chinese_terms"
        and bool(tags & {"chinese_terms", "zh-CN", "zh_terms"})
        or group == "unanswerable"
        and sample.get("expected_outcome") in ("unanswerable", "refuse")
    )


async def compare(owner, baseline_id, candidate_id, *, exploratory=False, group="all"):
    if group not in ("all", "pdf", "chinese_terms", "unanswerable"):
        raise AppError(422, "unknown_group", "不支持此评测分组")
    runs = []
    for run_id in (baseline_id, candidate_id):
        view = await get_run(owner, run_id)
        results = await get_results(owner, run_id)
        cost_records = [
            {
                **r,
                **{
                    key: r["sample"].get(key)
                    for key in ("family_ids", "family_id", "split", "case_type", "tags")
                },
                "metrics": r["metrics"] or {},
            }
            for r in results["items"]
        ]
        records = [r for r in cost_records if group_matches(r["sample"], group)]
        manifest = copy.deepcopy(view["manifest"])
        manifest["planned_sample_ids"] = sorted({r["sample_id"] for r in records})
        runs.append(
            {
                "status": view["status"],
                "stop_reason": view["stop_reason"],
                "manifest": manifest,
                "results": records,
                "max_cost_cny": view["max_cost_cny"],
                "cost_results": cost_records,
                "cost_planned_sample_ids": view["manifest"].get("planned_sample_ids"),
            }
        )
    incompatible = any(
        runs[0]["manifest"].get(k) != runs[1]["manifest"].get(k)
        for k in DEFAULT_PROTOCOL["compatibility_fields"]
    )
    if incompatible and not exploratory:
        raise conflict(
            "incompatible_comparison", "数据或指标协议不同，仅可显式选择探索对照"
        )
    comparison = await asyncio.to_thread(compare_runs, *runs)
    comparison.update(
        {
            "baseline_run_id": baseline_id,
            "candidate_run_id": candidate_id,
            "group": group,
            "exploratory": exploratory or not comparison["comparison_eligible"],
            "reason": "；".join(comparison["ineligibility_reasons"]),
        }
    )
    for metric in comparison["metrics"].values():
        metric["confidence_interval"] = metric.get("ci95")
        metric["unit"] = metric["baseline"].get(
            "unit", metric["candidate"].get("unit", "ratio")
        )
        metric["sample_count"] = comparison["sample_count"]
        metric["status"] = "ok" if metric.get("delta") is not None else "error"
    return comparison


def safe_csv(value):
    value = str(value if value is not None else "")
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
        else value
    )


async def export_run(owner, run_id, format):
    run = await get_run(owner, run_id)
    results = (await get_results(owner, run_id))["items"]
    if format == "jsonl":
        return "\n".join(dump(r) for r in results) + "\n", "application/x-ndjson"
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            [
                "sample_id",
                "repeat_index",
                "case_type",
                "status",
                "metric",
                "value",
                "metric_status",
                "reason",
            ]
        )
        for result in results:
            for name, metric in (result["metrics"] or {}).items():
                writer.writerow(
                    [
                        safe_csv(x)
                        for x in [
                            result["sample_id"],
                            result["repeat_index"],
                            result["case_type"],
                            result["status"],
                            name,
                            metric.get("value"),
                            metric.get("status"),
                            metric.get("reason"),
                        ]
                    ]
                )
        return "\ufeff" + stream.getvalue(), "text/csv"
    if format == "markdown":
        text = f"# 评测运行 {run_id}\n\n状态：{run['status']}；样本：{len(results)}。正式比较资格须另行核验。\n\n"
        for result in results:
            text += f"- {result['sample_id'].replace('`', '')} / {result['repeat_index']}: {result['status']}\n"
        return text, "text/markdown"
    raise AppError(422, "unsupported_export", "支持 jsonl、csv、markdown")
