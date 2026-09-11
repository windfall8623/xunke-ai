"""Executable B0 summary baseline, fenced to isolated evaluation only.

The original prompts/constants are loaded from a SHA-verified source archive. This
adapter preserves summary -> first 3000 code points -> original quiz prompt and the
historical empty-summary-on-error behavior. Storage, auth, logging and budgets use
isolated ports; the old application's repositories and learning services never run.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
import tarfile
from pathlib import Path

from app.rag.budget import BudgetLedger, count_tokens
from app.rag.contracts import (
    EvidencePack,
    PipelineConfig,
    QuizArtifact,
    QuizPayload,
    ValidationResult,
    stable_hash,
)
from app.rag.errors import (
    BudgetExceeded,
    ScopeRevoked,
    SourceUnavailable,
)
from app.rag.pipeline import reauthorize_scope
from app.rag.scope import normalize_spec, require_execution_scope


def _constant(archive: Path, suffix: str, name: str):
    with tarfile.open(archive, "r:gz") as bundle:
        matches = [
            m for m in bundle.getmembers() if m.isfile() and m.name.endswith(suffix)
        ]
        if len(matches) != 1 or matches[0].size > 256000:
            raise SourceUnavailable("Frozen legacy source file is missing or invalid")
        text = bundle.extractfile(matches[0]).read().decode("utf-8-sig")
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise SourceUnavailable("Frozen legacy source constant is unavailable")


class LegacyBaselineAdapter:
    def __init__(
        self,
        *,
        source_archive,
        archive_sha256: str,
        llm,
        retriever,
        reauthorize,
        summary_agent=None,
        web_provider=None,
        source_commit="7302ad2",
    ):
        self.archive = Path(source_archive)
        if hashlib.sha256(self.archive.read_bytes()).hexdigest() != archive_sha256:
            raise SourceUnavailable("Legacy source archive checksum changed")
        if llm is not None and getattr(llm, "max_retries", 0) != 0:
            raise ValueError("Legacy provider must disable SDK retries")
        self.archive_sha256, self.source_commit = archive_sha256, source_commit
        self.llm, self.retriever, self.reauthorize = llm, retriever, reauthorize
        self.summary_agent, self.web_provider = summary_agent, web_provider
        self.rag_prompt = _constant(
            self.archive, "app/prompts/rag_prompt.py", "RAG_AGENT_SYSTEM_PROMPT"
        )
        self.quiz_system = _constant(
            self.archive, "app/prompts/quiz_prompt.py", "QUIZ_SYSTEM_PROMPT"
        )
        self.quiz_human = _constant(
            self.archive, "app/prompts/quiz_prompt.py", "QUIZ_HUMAN_PROMPT"
        )
        self.context_template = _constant(
            self.archive, "app/prompts/quiz_prompt.py", "SEARCH_CONTEXT_TEMPLATE"
        )
        self.context_limit = _constant(
            self.archive, "app/services/rag_service.py", "MAX_CONTEXT_LENGTH"
        )
        self.agent_timeout = _constant(
            self.archive, "app/services/rag_service.py", "AGENT_TIMEOUT_SECONDS"
        )
        if self.context_limit != 3000 or self.agent_timeout != 60:
            raise SourceUnavailable("Legacy archive is not the frozen B0 protocol")

    def pipeline_config(self):
        from app.rag.registry import get_pipeline_config

        return get_pipeline_config(
            "legacy-summary-b0",
            legacy_source_archive_sha256=self.archive_sha256,
            legacy_source_commit=self.source_commit,
            generator_model=getattr(self.llm, "model_name", "configured"),
        )

    def _callbacks(self, ledger):
        from langchain_core.callbacks import BaseCallbackHandler

        class Admission(BaseCallbackHandler):
            raise_error = True
            run_inline = True

            def on_chat_model_start(self, serialized, messages, **kwargs):
                ledger.reserve(
                    "llm",
                    input_tokens=sum(
                        count_tokens(str(m.content))
                        for batch in messages
                        for m in batch
                    ),
                )

            def on_llm_start(self, serialized, prompts, **kwargs):
                ledger.reserve(
                    "llm", input_tokens=sum(count_tokens(prompt) for prompt in prompts)
                )

            def on_llm_end(self, response, **kwargs):
                usage = (response.llm_output or {}).get("token_usage", {})
                ledger.record_output(int(usage.get("completion_tokens", 0)))

        return [Admission()]

    def _build_agent(self, spec, scope, context, ledger):
        from langchain_core.runnables import RunnableLambda
        from langchain_core.tools import tool
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from langgraph.prebuilt import create_react_agent

        call_count = [0]

        @tool
        async def search_knowledge_base(query: str) -> str:
            """在用户明确选择的隔离评测资料中检索，返回原文片段。"""
            call_count[0] += 1
            if call_count[0] > 3:
                raise BudgetExceeded("Legacy baseline tool limit reached")
            await reauthorize_scope(self.reauthorize, scope)
            try:
                result = await self.retriever.retrieve_evidence(
                    query,
                    scope,
                    PipelineConfig(
                        retriever="legacy_dense", dense_top_k=4, final_top_k=4
                    ),
                    budget=ledger,
                )
                await reauthorize_scope(self.reauthorize, scope)
                return (
                    "\n\n".join(e.excerpt for e in result.evidence)
                    or "知识库中未检索到相关内容。"
                )
            except (BudgetExceeded, ScopeRevoked):
                raise
            except Exception:  # noqa: BLE001 - Preserve frozen B0 retrieval-failure semantics.
                return "知识库检索失败，未获取到内容。"

        selected_tools = [search_knowledge_base]
        if self.web_provider is not None and spec.source_policy in (
            "topic",
            "doc_plus_web",
        ):

            @tool
            async def tavily_search_basic(query: str) -> str:
                """在获准学习主题范围内获取公共网页资料。"""
                call_count[0] += 1
                if call_count[0] > 3:
                    raise BudgetExceeded("Legacy baseline tool limit reached")
                # Intentional privacy adaptation: never send model-rewritten private
                # document text to an external search engine, even for B0.
                evidence = await self.web_provider.retrieve(
                    spec.user_input, scope, context, budget=ledger
                )
                return "\n\n".join(e.excerpt for e in evidence)

            selected_tools.append(tavily_search_basic)
        if not callable(getattr(self.llm, "bind_tools", None)):
            raise SourceUnavailable(
                "Legacy summary provider must support metered tool binding"
            )
        bound_model = self.llm.bind_tools(selected_tools)

        async def invoke(messages, config=None, **kwargs):
            # This wrapper works with a metered provider that is not itself a
            # LangChain BaseChatModel; every actual call still enters that port.
            batch = (
                messages.to_messages() if hasattr(messages, "to_messages") else messages
            )
            await reauthorize_scope(self.reauthorize, scope)
            ledger.reserve(
                "llm",
                input_tokens=sum(
                    count_tokens(str(message.content)) for message in batch
                ),
            )
            response = await bound_model.ainvoke(batch)
            observed = getattr(response, "usage_metadata", None) or {}
            ledger.record_output(
                int(observed.get("output_tokens", count_tokens(str(response.content))))
            )
            await reauthorize_scope(self.reauthorize, scope)
            return response

        model = RunnableLambda(invoke).bind(
            tools=[convert_to_openai_tool(tool) for tool in selected_tools]
        )
        return create_react_agent(model, selected_tools, prompt=self.rag_prompt)

    async def run(self, spec, actor, context, scope, *, config=None) -> QuizArtifact:
        if context.mode != "evaluation":
            raise ScopeRevoked("Legacy B0 can run only in isolated evaluation")
        require_execution_scope(actor, context, scope)
        spec = normalize_spec(spec)
        config = config or self.pipeline_config()
        if (
            config.pipeline_version != "legacy-summary-b0"
            or config.legacy_source_archive_sha256 != self.archive_sha256
            or config.legacy_source_commit != self.source_commit
        ):
            raise SourceUnavailable(
                "Legacy baseline does not match this run's frozen source protocol"
            )
        await reauthorize_scope(self.reauthorize, scope)
        ledger = BudgetLedger(context.budget)
        agent = self.summary_agent or self._build_agent(spec, scope, context, ledger)
        try:
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [{"role": "user", "content": spec.user_input}]},
                    config={
                        "recursion_limit": 10,
                        "callbacks": self._callbacks(ledger)
                        if self.summary_agent
                        else [],
                    },
                ),
                timeout=min(self.agent_timeout, ledger.remaining_seconds),
            )
            messages = result.get("messages", [])
            summary = messages[-1].content if messages else ""
            summary = summary[: self.context_limit] if isinstance(summary, str) else ""
        except (BudgetExceeded, ScopeRevoked):
            raise
        except Exception:  # noqa: BLE001 - Preserve frozen B0 empty-summary fallback.
            summary = (
                ""  # Frozen historical behavior; never used in the production pipeline.
            )
        await reauthorize_scope(self.reauthorize, scope)
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = self.quiz_human.format(
            user_input=spec.user_input,
            question_count=spec.question_count,
            difficulty=spec.difficulty,
            search_context_section=self.context_template.format(search_context=summary)
            if summary
            else "",
        )
        ledger.reserve(
            "llm", input_tokens=count_tokens(prompt) + count_tokens(self.quiz_system)
        )
        response = await asyncio.wait_for(
            self.llm.ainvoke(
                [SystemMessage(content=self.quiz_system), HumanMessage(content=prompt)]
            ),
            timeout=ledger.remaining_seconds,
        )
        await reauthorize_scope(self.reauthorize, scope)
        raw = response.content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        payload = json.loads(fenced[1] if fenced else raw)
        for question in payload.get("questions", []):
            question.pop("image_url", None)
            question["citation_refs"] = []
            question["support_quotes"] = []
        quiz = QuizPayload.model_validate(payload)
        observed = getattr(response, "usage_metadata", None) or {}
        ledger.record_output(int(observed.get("output_tokens", count_tokens(raw))))
        manifest = {
            "source_archive_sha256": self.archive_sha256,
            "source_commit": self.source_commit,
            "max_context_characters": self.context_limit,
            "agent_timeout_seconds": self.agent_timeout,
            "dense_top_k": 4,
            "generator_model": getattr(self.llm, "model_name", "explicit-provider"),
            "adaptations": [
                "isolated authorized canonical source projection",
                "no learning/image/SQL side effects",
                "bounded calls and SDK retries disabled",
                "public search requires approved policy and topic",
                "legacy quotes remain unverified; no reconstructed citations",
            ],
        }
        return QuizArtifact(
            **quiz.model_dump(),
            artifact_id="legacy_" + stable_hash([context.run_id, manifest])[:32],
            run_id=context.run_id,
            owner_id=actor.owner_id,
            mode="evaluation",
            source_status="legacy_unverified",
            evidence_pack=EvidencePack(
                trace_id=context.run_id,
                policy=spec.source_policy,
                resolved_scope=scope,
                status="model_only",
                warnings=["legacy_summary_not_a_verbatim_citation"],
            ),
            pipeline_version="legacy-summary-b0",
            pipeline_config_hash=config.pipeline_config_hash,
            usage=ledger.snapshot(),
            validation=ValidationResult(passed=True, semantic_status="not_evaluated"),
            effective_config={
                "baseline": manifest,
                "pipeline": config.model_dump(mode="json"),
            },
        )
