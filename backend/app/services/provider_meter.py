"""Reserve before each external attempt; persist usage independently of job success."""

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError
from app.core.values import dump, load, now, uid
from app.llm.provider_errors import provider_failure
from app.services import budget_service, job_service

_job = ContextVar("provider_job", default=None)
logger = logging.getLogger(__name__)


@contextmanager
def execution(job):
    token = _job.set(job)
    try:
        yield
    finally:
        _job.reset(token)


def estimate(
    stage, input_tokens, output_tokens, *, input_token_details=None, reserve=False
):
    s = get_settings()
    if (
        stage == "llm"
        and s.llm_input_cny_per_million is not None
        and s.llm_output_cny_per_million is not None
    ):
        read_price = s.llm_cache_read_cny_per_million
        write_price = s.llm_cache_write_cny_per_million
        input_price = s.llm_input_cny_per_million
        if reserve:
            # The provider may bill a cache write above the ordinary input rate.
            input_price = max(
                price
                for price in (input_price, read_price, write_price)
                if price is not None
            )
        details = input_token_details or {}
        read, write = details.get("cache_read", 0), details.get("cache_creation", 0)
        if (read and read_price is None) or (write and write_price is None):
            return None
        return (
            (input_tokens - read - write) * input_price
            + read * (read_price or 0)
            + write * (write_price or 0)
            + output_tokens * s.llm_output_cny_per_million
        ) / 1_000_000
    if stage == "embedding" and s.embedding_cny_per_million is not None:
        return input_tokens * s.embedding_cny_per_million / 1_000_000
    return {
        "reranker": s.rerank_call_cny,
        "search": s.search_call_cny,
        "images": s.image_call_cny,
        "fetch": 0,
    }.get(stage)


def _reported_usage(raw):
    """Validate normalized LangChain usage without coercing invalid provider data."""
    fields = {"input_tokens": None, "output_tokens": None}
    details = {}
    valid = isinstance(raw, dict)
    if not valid:
        return {**fields, "input_token_details": details}, False, False
    for name in fields:
        value = raw.get(name)
        if type(value) is int and value >= 0:
            fields[name] = value
        else:
            valid = False
    provided_details = raw.get("input_token_details", {})
    if not isinstance(provided_details, dict):
        valid = False
    else:
        for name, value in provided_details.items():
            if not isinstance(name, str):
                valid = False
                continue
            if type(value) is int and value >= 0:
                details[name] = value
            else:
                details[name] = None
                valid = False
    read, creation = details.get("cache_read", 0), details.get("cache_creation", 0)
    if fields["input_tokens"] is not None and read is not None and creation is not None:
        if read + creation > fields["input_tokens"]:
            valid = False
    cache_parts = (
        details.get("ephemeral_5m_input_tokens", 0),
        details.get("ephemeral_1h_input_tokens", 0),
    )
    if creation is not None and all(part is not None for part in cache_parts):
        if sum(cache_parts) > creation:
            valid = False
    if "total_tokens" in raw:
        total = raw["total_tokens"]
        if (
            type(total) is not int
            or not valid
            or total != fields["input_tokens"] + fields["output_tokens"]
        ):
            valid = False
    cached = any(
        type(value) is int and value > 0 for value in (read, creation, *cache_parts)
    )
    return {**fields, "input_token_details": details}, valid, cached


def _chat_usage(normalized, metadata):
    """Prefer raw provider counters: SDK defaults are not observed usage."""
    if not isinstance(metadata, dict):
        return _reported_usage(normalized)
    native = "usage" in metadata
    if not native and "token_usage" not in metadata:
        return _reported_usage(normalized)
    raw = metadata.get("usage" if native else "token_usage")
    if not isinstance(raw, dict):
        return _reported_usage(None)
    details, valid = {}, True
    inputs = raw.get("input_tokens" if native else "prompt_tokens")
    outputs = raw.get("output_tokens" if native else "completion_tokens")
    if native:
        for source, target in (
            ("cache_read_input_tokens", "cache_read"),
            ("cache_creation_input_tokens", "cache_creation"),
        ):
            # Optional SDK fields serialize as null when omitted by the API.
            if raw.get(source) is not None:
                details[target] = raw[source]
        ttl = raw.get("cache_creation")
        if ttl is not None:
            if not isinstance(ttl, dict):
                valid = False
            else:
                for name in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
                    if ttl.get(name) is not None:
                        details[name] = ttl[name]
        parts = (inputs, details.get("cache_read", 0), details.get("cache_creation", 0))
        inputs = sum(parts) if all(type(v) is int and v >= 0 for v in parts) else None
    else:
        prompt_details = raw.get("prompt_tokens_details")
        if prompt_details is not None:
            if not isinstance(prompt_details, dict):
                valid = False
            elif prompt_details.get("cached_tokens") is not None:
                details["cache_read"] = prompt_details["cached_tokens"]
        if "prompt_cache_hit_tokens" in raw:
            hit = raw["prompt_cache_hit_tokens"]
            if "cache_read" in details and details["cache_read"] != hit:
                valid = False
            details["cache_read"] = hit
        if "prompt_cache_miss_tokens" in raw:
            miss = raw["prompt_cache_miss_tokens"]
            if (
                type(inputs) is not int
                or type(miss) is not int
                or not 0 <= miss <= inputs
            ):
                valid = False
            elif "cache_read" in details:
                hit = details["cache_read"]
                if type(hit) is not int or hit + miss != inputs:
                    valid = False
            else:
                details["cache_read"] = inputs - miss
    usage = {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "input_token_details": details,
    }
    if "total_tokens" in raw:
        usage["total_tokens"] = raw["total_tokens"]
    usage, known, cached = _reported_usage(usage)
    return usage, valid and known, cached


async def call_external(
    stage, call, *, input_upper=0, output_upper=0, purpose=None, model=None
):
    job = _job.get()
    if job is None:
        raise RuntimeError("External model calls require a durable job context")
    if job.get("kind") == "learning_project":
        raise AppError(
            409,
            "learning_projection_external_call_forbidden",
            "学习进度投影不能调用外部模型或服务",
        )
    if job.get("scope"):
        from app.services.source_service import reauthorize_scope

        await reauthorize_scope(job["scope"])
    s = get_settings()
    day = now().date().isoformat()
    call_id = uid("call")
    cost = estimate(stage, input_upper, output_upper, reserve=True)
    if job["mode"] == "evaluation" and cost is None:
        raise AppError(409, "pricing_required", "评测费用上限需要配置对应模型的价格")
    if cost is not None and cost < 0:
        raise ValueError("Provider prices cannot be negative")
    if stage == "llm":
        cap = (
            5
            if job["kind"] in {"quiz", "qa", "eval_sample", "practice_generate"}
            else 3
            if job["kind"] == "course_lesson"
            else 2
        )
        daily = s.user_daily_llm_calls
        global_daily = s.global_daily_llm_calls
    elif stage == "images":
        cap = 10
        daily = s.image_gen_daily_limit
        global_daily = 10000
    else:
        cap = (
            2000
            if job["kind"] == "ingest"
            else {"embedding": 100, "reranker": 2, "search": 2, "fetch": 10}.get(
                stage, 1
            )
        )
        daily = 2000
        global_daily = 20000
    prefix = "evaluation" if job["mode"] == "evaluation" else "production"
    counts = [
        (f"{prefix}:user:{job['user_id']}:{day}:{stage}", daily),
        (
            f"{prefix}:global:{day}:{stage}",
            s.eval_daily_llm_calls
            if prefix == "evaluation" and stage == "llm"
            else global_daily,
        ),
        (f"job:{job['task_id']}:{stage}", cap),
    ]
    if stage == "llm" and purpose == "reranker":
        counts.append(
            (
                f"job:{job['task_id']}:reranker",
                1 if job["kind"] == "practice_generate" else 2,
            )
        )
    logical_id = None
    async with transaction() as conn:
        current = await job_service.locked_job(job, conn)
        if current["kind"] == "practice_generate":
            # Use the locked persisted identity. It is allocated by the create
            # service and shared by every retry task/attempt for this practice.
            logical_id = current["request"].get("generation_request_id")
            if (
                current["operation"] != "practice.generate"
                or not isinstance(logical_id, str)
                or not logical_id
                or logical_id != current["request"].get("practice_id")
            ):
                raise AppError(
                    409, "practice_generation_changed", "练习生成任务身份不完整"
                )
            from app.practice.grading_config import require_generation_types

            require_generation_types(
                current["request"].get("spec", {}).get("question_types", [])
            )
            if stage == "llm":
                counts.append((f"practice_generate:{logical_id}:llm", 5))
        elif current["kind"] == "practice_grade":
            from app.services.practice_grading_service import (
                authorize_grading_execution,
            )

            state = await authorize_grading_execution(job, conn=conn)
            if stage != "llm" or purpose != "practice_grading":
                raise AppError(
                    409, "grading_call_forbidden", "评分任务只能调用固定评分模型"
                )
            logical_id = state.snapshot.grading_request_id
            counts.append((f"{current['mode']}:practice_grade:{logical_id}:llm", 2))
        elif current["kind"] == "eval_sample" and (
            purpose
            in {"practice_grading", "practice_generation", "practice_validation"}
            or current["request"].get("grading_request_id")
            or current["request"].get("generation_request_id")
        ):
            grading = (
                bool(current["request"].get("grading_request_id"))
                or purpose == "practice_grading"
            )
            field = "grading_request_id" if grading else "generation_request_id"
            logical_id = current["request"].get(field)
            if (
                current["mode"] != "evaluation"
                or current["operation"] != "eval.sample"
                or not isinstance(logical_id, str)
                or not 1 <= len(logical_id) <= 64
                or current["request"] != job.get("request")
                or current["scope"] != job.get("scope")
                or grading
                and current["request"].get("generation_request_id")
            ):
                raise AppError(
                    409, "grading_identity_changed", "评测评分任务身份不完整"
                )
            if grading:
                if stage != "llm" or purpose != "practice_grading":
                    raise AppError(
                        409, "grading_call_forbidden", "评分任务只能调用固定评分模型"
                    )
                counts.append((f"evaluation:practice_grade:{logical_id}:llm", 2))
            else:
                if stage not in {"llm", "embedding", "reranker"} or (
                    stage == "llm"
                    and purpose
                    not in {"practice_generation", "practice_validation", "reranker"}
                ):
                    raise AppError(
                        409,
                        "generation_call_forbidden",
                        "练习评测只能调用固定文档生成服务",
                    )
                if stage in {"llm", "reranker"}:
                    counts.append(
                        (f"evaluation:practice_generate:{logical_id}:model_calls", 5)
                    )
                if stage == "reranker" or purpose == "reranker":
                    counts.append(
                        (f"evaluation:practice_generate:{logical_id}:reranker", 1)
                    )
            evaluator = await fetch_one(
                "SELECT role FROM users WHERE id=%s FOR SHARE",
                (current["user_id"],),
                conn=conn,
            )
            if not evaluator or evaluator["role"] != "evaluator":
                raise AppError(403, "evaluation_permission_required", "评测权限已撤销")
            if current["request"].get("result_id"):
                from app.services.evaluation_scoring import _locked_context

                prepared = await _locked_context(current["request"]["result_id"], conn)
                if prepared is None:
                    raise AppError(409, "evaluation_busy", "评测结果正由其他进程处理")
                result_row, run, _, sample = prepared
                manifest = load(run["manifest_json"])
                if (
                    run["owner_id"] != current["user_id"]
                    or run["run_id"] != current["request"].get("run_id")
                    or sample["case_type"]
                    != ("answer_grading" if grading else "practice_generation")
                    or grading
                    and sample["question_type"] != "short_answer"
                    or manifest.get("source_scopes", {}).get(result_row["sample_id"])
                    != current["scope"]
                    or result_row["status"] not in {"queued", "running"}
                ):
                    raise AppError(
                        409, "evaluation_identity_changed", "评测任务身份或范围已改变"
                    )
        if job.get("scope"):
            await reauthorize_scope(job["scope"], conn=conn)
        if job["kind"] == "ingest":
            from app.services.source_service import owned_document

            source = await owned_document(
                job["user_id"],
                job["request"]["doc_id"],
                purpose=job["request"]["purpose"],
                conn=conn,
                lock=True,
            )
            if source["document_revision"] != job["request"]["document_revision"]:
                raise AppError(409, "source_changed", "资料构建已被更新")
        await budget_service.reserve_budget(call_id, "calls", 1, counts, conn=conn)
        await budget_service.settle_budget(call_id, "calls", 1, conn=conn)
        if cost is not None and cost > 0:
            if job["mode"] == "evaluation" and job["kind"] == "ingest":
                accounts = [
                    (
                        f"evaluation_ingest:user:{job['user_id']}:{day}:cny",
                        s.eval_ingest_daily_cost_cny,
                    ),
                    (f"evaluation_ingest:global:{day}:cny", s.eval_daily_cost_cny),
                ]
            elif job["mode"] == "evaluation":
                run_id = job["request"]["run_id"]
                run = await fetch_one(
                    "SELECT max_cost_cny,status FROM eval_runs WHERE run_id=%s",
                    (run_id,),
                    conn=conn,
                )
                if not run or run["status"] in ("cancelled", "failed"):
                    raise AppError(409, "run_stopped", "评测已停止")
                accounts = [
                    (f"eval_run:{run_id}:cny", run["max_cost_cny"]),
                    (f"evaluation:global:{day}:cny", s.eval_daily_cost_cny),
                ]
            else:
                accounts = [
                    (
                        f"production:user:{job['user_id']}:{day}:cny",
                        s.production_daily_cost_cny,
                    ),
                    (f"production:global:{day}:cny", s.global_daily_cost_cny),
                ]
            # Decimal storage is six fractional digits; round upwards for ceilings.
            ceiling = Decimal(str(cost)).quantize(
                Decimal(".000001"), rounding="ROUND_CEILING"
            )
            await budget_service.reserve_budget(
                call_id, "cny", ceiling, accounts, conn=conn
            )
        await execute(
            "INSERT INTO provider_calls(call_id,operation_id,owner_id,mode,stage,status,usage_json) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                call_id,
                job["task_id"],
                job["user_id"],
                job["mode"],
                stage,
                "reserved",
                dump(
                    {
                        "pricing_version": s.pricing_version,
                        "reserved_cost_cny": cost,
                        "attempt": job["attempt"],
                        "purpose": purpose,
                        "model": model,
                        "logical_request_id": logical_id,
                    }
                ),
            ),
            conn=conn,
        )
    started = time.monotonic()
    try:
        result = await call()
        usage = getattr(result, "usage_metadata", None) or {}
        if isinstance(result, httpx.Response):
            result.raise_for_status()
            try:
                observed = result.json().get("usage", {})
                usage = {
                    "input_tokens": observed.get(
                        "prompt_tokens", observed.get("total_tokens")
                    ),
                    "output_tokens": observed.get("completion_tokens", 0),
                    "input_token_details": observed.get("input_token_details", {}),
                }
            except (ValueError, AttributeError):
                usage = {}
        metadata = getattr(result, "response_metadata", None)
        usage, known, _cached = (
            _chat_usage(usage, metadata) if stage == "llm" else _reported_usage(usage)
        )
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        actual = (
            estimate(
                stage,
                input_tokens,
                output_tokens,
                input_token_details=usage["input_token_details"],
            )
            if known
            else cost
            if stage in ("search", "reranker", "images", "fetch")
            else None
        )
        if actual is not None and cost is not None and actual > cost + 0.000001:
            actual = None  # Unexpected usage cannot be silently clipped or called a verified bill.
        record = {
            "call_id": call_id,
            "stage": stage,
            "attempt": job["attempt"],
            "status": "completed",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_token_details": usage["input_token_details"],
            "estimated_input_tokens": input_upper,
            "cost_cny": actual,
            "reserved_cost_cny": cost,
            "cost_status": "estimated" if actual is not None else "unknown",
            "pricing_version": s.pricing_version,
            "purpose": purpose,
            "model": model,
            "logical_request_id": logical_id,
            "provider_model": (
                metadata.get("model") or metadata.get("model_name")
                if isinstance(metadata, dict)
                else None
            ),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        async with transaction() as conn:
            await execute(
                "UPDATE provider_calls SET status='completed',usage_json=%s WHERE call_id=%s",
                (dump(record), call_id),
                conn=conn,
            )
            if cost is not None and cost > 0:
                await budget_service.settle_budget(
                    call_id, "cny", actual, unknown=actual is None, conn=conn
                )
        return result
    except BaseException as exc:
        failure = provider_failure(exc)
        record = {
            "call_id": call_id,
            "stage": stage,
            "attempt": job["attempt"],
            "status": "unknown",
            "cost_cny": None,
            "cost_status": "unknown",
            "reserved_cost_cny": cost,
            "purpose": purpose,
            "model": model,
            "logical_request_id": logical_id,
            "error_code": failure.code if failure else None,
            "error_type": type(exc).__name__,
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        async with transaction() as conn:
            await execute(
                "UPDATE provider_calls SET status='unknown',usage_json=%s WHERE call_id=%s",
                (dump(record), call_id),
                conn=conn,
            )
            if cost is not None and cost > 0:
                await budget_service.settle_budget(
                    call_id, "cny", unknown=True, conn=conn
                )
        if failure is not None:
            logger.warning(
                "Provider call failed call_id=%s stage=%s code=%s error_type=%s",
                call_id,
                stage,
                failure.code,
                type(exc).__name__,
            )
            raise failure from exc
        raise


class MeteredChat:
    max_retries = 0

    def __init__(self, llm, *, purpose="generation", output_upper=4096):
        self.llm = llm
        self.purpose = purpose
        self.output_upper = output_upper
        self.model_name = "configured"
        current, seen = llm, set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            name = getattr(current, "model_name", None) or getattr(
                current, "model", None
            )
            if isinstance(name, str) and name:
                self.model_name = name
                break
            current = getattr(current, "bound", None)

    def bind_tools(self, tools, **kwargs):
        return MeteredChat(
            self.llm.bind_tools(tools, **kwargs),
            purpose=self.purpose,
            output_upper=self.output_upper,
        )

    async def ainvoke(self, messages):
        from app.rag.budget import count_tokens

        input_upper = 32
        for message in messages:
            content = message.content
            input_upper += count_tokens(
                content if isinstance(content, str) else dump(content)
            )
            if tool_calls := getattr(message, "tool_calls", None):
                input_upper += count_tokens(dump(tool_calls))
        bound_kwargs = getattr(self.llm, "kwargs", {})
        if isinstance(bound_kwargs, dict) and bound_kwargs.get("tools"):
            input_upper += count_tokens(dump(bound_kwargs["tools"]))
        return await call_external(
            "llm",
            lambda: self.llm.ainvoke(messages),
            input_upper=input_upper,
            output_upper=self.output_upper,
            purpose=self.purpose,
            model=self.model_name,
        )


class MeteredHTTP:
    """Embedding adapter dependency; meters every batch request, not just the outer call."""

    async def post(self, url, **kwargs):
        data = kwargs.get("json", {})
        stage = "embedding"
        input_upper = sum(len(text.encode("utf-8")) for text in data.get("input", []))

        async def send():
            async with httpx.AsyncClient(
                timeout=get_settings().provider_timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                return await client.post(url, **kwargs)

        return await call_external(stage, send, input_upper=input_upper)
