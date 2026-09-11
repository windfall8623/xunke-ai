"""Read-only price scenarios, deliberately separate from frozen run accounting.

This module neither instantiates providers nor reserves money. Token scenarios
are explicit assumptions, not predictions of observed usage or guaranteed bounds.
"""

from app.core.config import get_settings
from app.core.errors import conflict
from app.core.values import digest, dump, load
from app.services import eval_dataset_service as datasets


def _component(stage, reason):
    return {
        "stage": stage,
        "status": "not_applicable",
        "reason": reason,
        "first_attempt_cny": None,
        "retry_scenario_cny": None,
        "first_attempt_calls": 0,
        "retry_scenario_calls": 0,
        "first_attempt_input_tokens": 0,
        "first_attempt_output_tokens": 0,
        "retry_scenario_input_tokens": 0,
        "retry_scenario_output_tokens": 0,
        "prices": {},
        "missing_prices": [],
        "assumptions": [],
    }


def _unknown(item, reason):
    item.update(
        status="unknown", reason=reason, first_attempt_cny=None, retry_scenario_cny=None
    )


def _add(item, *, first, retry, prices, input_key=None, output_key=None, call_key=None):
    # Each usage tuple is (calls, input tokens, output tokens), including repeats.
    required = [key for key in (input_key, output_key, call_key) if key]
    item["prices"].update({key: prices.get(key) for key in required})
    missing = [key for key in required if prices.get(key) is None]
    item["missing_prices"] = sorted(set(item["missing_prices"] + missing))
    if missing:
        _unknown(item, "缺少对应单价，不能计算该阶段费用。")
    elif item["status"] == "not_applicable":
        item.update(
            status="estimated",
            reason=None,
            first_attempt_cny=0.0,
            retry_scenario_cny=0.0,
        )
    for label, (calls, inputs, outputs) in (
        ("first_attempt", first),
        ("retry_scenario", retry),
    ):
        item[f"{label}_calls"] += calls
        item[f"{label}_input_tokens"] += inputs
        item[f"{label}_output_tokens"] += outputs
        if item["status"] == "estimated":
            cost = (
                (inputs * prices[input_key] / 1_000_000 if input_key else 0)
                + (outputs * prices[output_key] / 1_000_000 if output_key else 0)
                + (calls * prices[call_key] if call_key else 0)
            )
            item[f"{label}_cny"] = round(item[f"{label}_cny"] + cost, 8)


def estimate_cost(samples, config, scorer, settings, *, repeat_count):
    retrieval = _component(
        "retrieval", "本运行没有收费检索调用；本地词法检索不计 provider 费用。"
    )
    generation = _component(
        "generation", "没有出题、练习生成或问答样本，不适用生成费用。"
    )
    grading = _component("grading", "没有答案判分样本，不适用被测判分模型费用。")
    scoring = _component(
        "scoring", "确定性指标、人工复核或无可引用上下文，不适用模型评分费用。"
    )
    indexing = _component(
        "indexing", "已有资料索引在运行前构建，其费用不包含在本次运行估算内。"
    )
    components = [retrieval, generation, scoring, indexing]
    if any(sample.get("case_type") == "answer_grading" for sample in samples):
        components.insert(2, grading)
    if not samples:
        _unknown(generation, "没有样本数据，无法估算用量。")
    prices = settings.model_dump()
    prediction_attempts = max(1, settings.job_max_attempts)
    # Matches evaluation_scoring.MAX_SCORING_ATTEMPTS; no SDK retries are enabled.
    scoring_attempts = 2
    for sample in samples:
        kind = sample.get("case_type")
        if kind == "policy":
            continue
        if kind == "answer_grading":
            question_type = sample.get("question_type")
            if question_type in {"cloze", "numeric"}:
                _add(grading, first=(0, 0, 0), retry=(0, 0, 0), prices={})
                grading["assumptions"].append(
                    "填空和数值题使用确定性规则，不调用判分模型，也不调用检索。"
                )
            elif question_type == "short_answer":
                output = settings.practice_grading_output_tokens
                inputs = settings.practice_grading_context_window - output
                _add(
                    grading,
                    first=(repeat_count, inputs * repeat_count, output * repeat_count),
                    retry=(
                        2 * repeat_count,
                        2 * inputs * repeat_count,
                        2 * output * repeat_count,
                    ),
                    prices=prices,
                    input_key="llm_input_cny_per_million",
                    output_key="llm_output_cny_per_million",
                )
                grading["assumptions"].append(
                    f"被测短解释判分器按配置输入预算 {inputs}、输出 {output} token 的无缓存情景估算；"
                    "同一逻辑判分请求最多 2 次模型调用，重试不增加上限。"
                )
                grading["assumptions"].append(
                    "只使用已给定证据，不额外检索；独立外部 Judge 与被测判分器分开计价，本轮新题型使用确定性指标和人工复核。"
                )
            else:
                _unknown(grading, "缺少有效题型，无法估算判分模型用量。")
            continue
        if kind not in ("retrieval", "quiz", "qa", "practice_generation"):
            _unknown(generation, "样本类型不支持用量估算。")
            continue
        if (
            kind in {"qa", "practice_generation"}
            and config.pipeline_version == "legacy-summary-b0"
        ):
            _unknown(generation, "B0 历史出题方案不支持问答或新题型评测。")
            continue
        has_docs = bool(sample.get("source_refs"))
        source_policy = sample.get(
            "source_policy", "strict_docs" if has_docs else "topic"
        )
        web = (
            kind == "quiz"
            and source_policy in ("topic", "doc_plus_web")
            and (settings.enable_web_search and bool(settings.tavily_api_key))
        )
        legacy = kind == "quiz" and config.pipeline_version == "legacy-summary-b0"
        query = (
            "；".join(sample.get("spec", {}).get("objectives", []))
            if kind == "practice_generation"
            else sample.get(
                {"retrieval": "query", "quiz": "user_input", "qa": "question"}[kind]
            )
        )
        if not isinstance(query, str) or not query.strip():
            _unknown(
                retrieval if kind == "retrieval" else generation,
                "缺少请求文本，无法估算 token 用量。",
            )
            continue
        query_tokens = len(query.encode("utf-8"))
        first_chat_rankings, retry_chat_rankings = 0, 0
        if legacy:
            _unknown(
                retrieval, "B0 的历史 Agent 工具调用由模型决定，暂无可比用量依据。"
            )
            _unknown(generation, "B0 的摘要和出题调用尚无可靠 token 用量模型。")
        if web:
            _unknown(
                retrieval, "网页搜索和临时索引取决于尚未抓取的正文长度，费用未知。"
            )
        if has_docs and not legacy:
            first_queries = repeat_count
            retry_queries = prediction_attempts * repeat_count
            retrieval_tokens = query_tokens
            if kind == "quiz":
                catalog = config.coverage_strategy != "single-goal-v1"
                subqueries = config.max_subqueries if catalog else 1
                title_tokens = 128 if catalog else 0
                retrieval_tokens += title_tokens
                retry_queries *= subqueries * config.max_retrieval_rounds
                retrieval["assumptions"].append(
                    f"出题检索按首轮 1 个查询；重试情景每次任务最多 {subqueries} 个子查询 × "
                    f"{config.max_retrieval_rounds} 轮；每条查询另假设 {title_tokens} 个章节标题 token。"
                )
            if config.retriever != "bm25":
                _add(
                    retrieval,
                    first=(first_queries, retrieval_tokens * first_queries, 0),
                    retry=(retry_queries, retrieval_tokens * retry_queries, 0),
                    prices=prices,
                    input_key="embedding_cny_per_million",
                )
                retrieval["assumptions"].append(
                    "查询以 UTF-8 字节数离线估计 token，每次查询调用一次 embedding。"
                )
            if config.reranker.provider == "llm":
                ranking = config.reranker.llm
                # Ranking follows the candidate merge, once per retrieval round.
                # Persisted per-job admission includes failed attempts and caps
                # all chat ranking at two calls across prediction retries.
                first_chat_rankings = 1
                retry_chat_rankings = min(
                    2,
                    prediction_attempts
                    * (config.max_retrieval_rounds if kind == "quiz" else 1),
                )
                first_rankings = first_chat_rankings * repeat_count
                retry_rankings = retry_chat_rankings * repeat_count
                _add(
                    retrieval,
                    first=(
                        first_rankings,
                        ranking.max_input_tokens * first_rankings,
                        ranking.max_output_tokens * first_rankings,
                    ),
                    retry=(
                        retry_rankings,
                        ranking.max_input_tokens * retry_rankings,
                        ranking.max_output_tokens * retry_rankings,
                    ),
                    prices=prices,
                    input_key="llm_input_cny_per_million",
                    output_key="llm_output_cny_per_million",
                )
                retrieval["assumptions"].append(
                    f"LLM 重排使用 {ranking.provider}/{ranking.model}，按生成模型的输入/输出单价计费；"
                    f"每次按配置的 {ranking.max_input_tokens} 输入 / {ranking.max_output_tokens} 输出 token 估计。"
                    "候选片段长度尚未读取，这是无缓存且用满重排提示预算的费用情景。"
                )
                retrieval["assumptions"].append(
                    "假设检索有候选结果；每轮合并章节候选后重排一次，任务累计最多 2 次，"
                    "与生成及语义校验共享累计 5 次 LLM 调用额度，不另按 BGE/Qwen 的每次价格收费。"
                )
            elif config.reranker.provider != "none":
                _add(
                    retrieval,
                    first=(first_queries, 0, 0),
                    retry=(min(2 * repeat_count, retry_queries), 0, 0),
                    prices=prices,
                    call_key="rerank_call_cny",
                )
                retrieval["assumptions"].append(
                    "假设每次检索都有候选结果，调用一次远程重排；任务累计重排上限为 2 次。"
                )
        if kind == "qa":
            history = sample.get("history", [])
            if not has_docs:
                _unknown(generation, "问答需要明确选择的资料范围。")
                continue
            # QA has one retrieval round and one attempt per stage. Rewrite is
            # used only for bounded complete history; semantic validation is
            # mandatory even if the selected retrieval config disables it.
            rewrite = int(bool(history))
            history_tokens = sum(
                len(turn.get("question", "").encode("utf-8"))
                + len(turn.get("answer", "").encode("utf-8"))
                + 64
                for turn in history
            )
            output = 4096  # build_runtime's LangChainQaGenerator output limit.
            inputs = query_tokens + config.context_token_budget + 2048
            first_calls = 2 + rewrite
            first_inputs = (
                inputs * 2 + output + rewrite * (query_tokens + history_tokens + 2048)
            )
            max_calls = min(
                5 - retry_chat_rankings,
                config.max_llm_calls * prediction_attempts - retry_chat_rankings,
                first_calls * prediction_attempts,
            )
            if config.max_llm_calls < first_calls + first_chat_rankings:
                _unknown(
                    generation,
                    "调用上限不足以完成问答改写、重排、回答及必需的语义验证。",
                )
            else:
                _add(
                    generation,
                    first=(
                        first_calls * repeat_count,
                        first_inputs * repeat_count,
                        output * first_calls * repeat_count,
                    ),
                    retry=(
                        max_calls * repeat_count,
                        max(inputs + output, query_tokens + history_tokens + 2048)
                        * max_calls
                        * repeat_count,
                        output * max_calls * repeat_count,
                    ),
                    prices=prices,
                    input_key="llm_input_cny_per_million",
                    output_key="llm_output_cny_per_million",
                )
            generation["assumptions"].append(
                f"问答每次仅检索 1 轮；有历史时至多改写 1 次，回答与必需语义校验各 1 次，首轮合计 {first_calls} 次生成调用。"
                f"每次回答输入假设为问题 UTF-8 字节数 + {config.context_token_budget} 个上下文 token + 2048 个提示词/JSON token，"
                f"校验另含一份输出；每次输出按 {output} token。历史仅计入改写输入。"
            )
            generation["assumptions"].append(
                f"问答重试情景生成最多 {max_calls} 次，另计 {retry_chat_rankings} 次模型重排；共享任务累计 5 次调用额度。"
                "假设检索到证据且走完回答与校验；澄清、资料不足、取消、故障可能提前结束。语义评测未校准，不估计外部 Judge 费用。"
            )
            continue
        if kind not in {"quiz", "practice_generation"}:
            continue
        if not legacy:
            # Current worker limits output to 4096 and all LLM attempts per job to 5.
            output = (
                config.output_token_reserve
                if kind == "practice_generation"
                else min(config.output_token_reserve, 4096)
            )
            context = config.context_token_budget if has_docs or web else 0
            inputs = query_tokens + context + 2048
            semantic = int(
                kind == "practice_generation" or config.require_semantic_validation
            )
            first_calls = 1 + semantic
            max_calls = min(
                5 - retry_chat_rankings,
                config.max_llm_calls * prediction_attempts - retry_chat_rankings,
                config.max_generation_attempts * first_calls * prediction_attempts,
            )
            if config.max_llm_calls < first_calls + first_chat_rankings:
                _unknown(generation, "调用上限不足以完成重排、出题及所需语义验证。")
            else:
                _add(
                    generation,
                    first=(
                        first_calls * repeat_count,
                        (inputs * first_calls + semantic * output) * repeat_count,
                        output * first_calls * repeat_count,
                    ),
                    retry=(
                        max_calls * repeat_count,
                        (inputs + semantic * output) * max_calls * repeat_count,
                        output * max_calls * repeat_count,
                    ),
                    prices=prices,
                    input_key="llm_input_cny_per_million",
                    output_key="llm_output_cny_per_million",
                )
            generation["assumptions"].append(
                f"每次出题输入假设为请求 UTF-8 字节数 + {context} 个上下文 token + 2048 个提示词/JSON token；"
                f"每次调用输出按 {output} token。语义验证另含一份出题输出。"
            )
            generation["assumptions"].append(
                f"每份样本首轮 {first_calls} 次调用（包含语义验证）；重试情景最多 {max_calls} 次，"
                f"另在检索阶段计入首轮 {first_chat_rankings} 次、重试情景 {retry_chat_rankings} 次模型重排，"
                "合计遵守任务累计 5 次 LLM 调用限制。"
            )
            generation["assumptions"].append(
                "生成费用按无提示缓存的输入/输出单价估算，不预测缓存命中率；"
                "实际费用根据完整 provider 用量和已配置的缓存读写单价结算，缺少单价或完整用量时保留未知。"
            )
        external = scorer.get("external_judge")
        if external and kind == "quiz" and (has_docs or web) and not legacy:
            count = sample.get("question_count", 5)
            if type(count) is not int or count < 1:
                _unknown(scoring, "缺少有效题量，评分用量未知。")
                continue
            first_calls = min(count * 2, external["max_llm_calls"]) * repeat_count
            retry_calls = first_calls * scoring_attempts
            _add(
                scoring,
                first=(
                    first_calls,
                    first_calls * external["max_input_tokens"],
                    first_calls * external["max_output_tokens"],
                ),
                retry=(
                    retry_calls,
                    retry_calls * external["max_input_tokens"],
                    retry_calls * external["max_output_tokens"],
                ),
                prices=external["price_table"],
                input_key="input_cny_per_million",
                output_key="output_cny_per_million",
            )
            scoring["assumptions"].append(
                f"假设每题有可评分引用，每题 2 次 Ragas 调用；每次评分最多 {external['max_llm_calls']} 次调用，"
                f"最多 {scoring_attempts} 次评分尝试。若调用上限不足，仅覆盖部分题目。"
            )
            scoring["assumptions"].append(
                f"每次评分调用按配置的 {external['max_input_tokens']} 输入 / {external['max_output_tokens']} 输出 token；"
                f"单价日期 {external['price_table']['effective_date']}。无引用的题目跳过，实际费用可能更低。"
            )
    for item in components:
        item["assumptions"] = list(dict.fromkeys(item["assumptions"]))
    status = (
        "unknown"
        if any(c["status"] == "unknown" for c in components)
        else (
            "estimated"
            if any(c["status"] == "estimated" for c in components)
            else "not_applicable"
        )
    )
    return {
        "status": status,
        "method": "configured_price_scenarios_v1",
        "currency": "CNY",
        "not_a_bill": True,
        "pricing_version": settings.pricing_version,
        "sample_count": len(samples),
        "repeat_count": repeat_count,
        "planned_executions": len(samples) * repeat_count,
        **{
            key: round(sum(c[key] or 0 for c in components), 8)
            if status == "estimated"
            else None
            for key in ("first_attempt_cny", "retry_scenario_cny")
        },
        "components": components,
        "assumptions": [
            f"已乘以全部 {repeat_count} 次重复；重试情景包括最多 {prediction_attempts} 次预测任务尝试及 "
            f"{scoring_attempts} 次评分尝试。失败、取消、预算或限流可能提前停止。",
            "这是配置单价和假定 token 用量的两种费用情景，不是实际账单、预算上限或保证的上下界。",
            "未执行 provider 调用、未创建运行、未预留费用；不验证运行依赖是否就绪。",
            "不含运行前资料建索引、人工复核、服务器及存储成本；评测不会生成配图。",
        ],
    }


async def preview_run_cost(actor, query):
    from app.services.evaluation_service import pipeline_config, scoring_config

    dataset = await datasets.dataset_row(
        actor.owner_id, query.dataset_id, query.dataset_version
    )
    if dataset["status"] != "frozen":
        raise conflict("dataset_not_frozen", "请先完成人工复核并冻结数据集")
    manifest, samples = load(dataset["manifest_json"]), load(dataset["samples_json"])
    if digest(dump({"manifest": manifest, "samples": samples})) != dataset["checksum"]:
        raise conflict("dataset_checksum_mismatch", "数据集校验和不一致")
    return estimate_cost(
        samples,
        pipeline_config(query.pipeline_id),
        scoring_config(query.judge_profile_id),
        get_settings(),
        repeat_count=query.repeat_count,
    )
