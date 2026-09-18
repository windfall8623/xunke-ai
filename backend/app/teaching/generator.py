"""One generation and at most one schema repair, both metered and deadline-bound."""

import asyncio
import json
import re
from typing import Literal, TypedDict

from pydantic import ValidationError

from app.core.errors import AppError
from app.core.values import dump
from app.llm.responses import response_text
from app.rag.budget import count_tokens
from app.rag.errors import BudgetExceeded
from app.teaching.contracts import strip_invalid_visuals
from app.teaching.contracts_v2 import CourseCriterionDraft, TeachUnitV2
from app.teaching.prompts import INPUT_LIMIT, PROMPT_VERSION, system_prompt, teaching_skill
from app.teaching.protocol import V1, V2, draft_hash, parse_course_draft, parse_lesson_draft
from app.teaching.quality import TeachingDraftInvalid, require_lesson_alignment, safe_feedback_codes, validation_codes


class GeneratedTeachingArtifact(TypedDict):
    draft: dict
    evidence: dict
    draft_hash: str
    skill_version: str
    skill_hash: str
    effective_config: dict


class LessonBlockPreview:
    """Only structurally complete, reference-owned v2 blocks reach the private preview.

    Publication still requires the whole draft, the Reviewer and the final
    application checks. A skipped or failing block never blocks generation.
    """

    def __init__(self, preview, *, source_policy, criterion_refs, evidence_refs):
        self.preview = preview
        self.source_policy = source_policy
        self.criterion_refs = set(criterion_refs)
        self.evidence_refs = set(evidence_refs)
        self.sent = []

    def _checked(self, raw):
        from app.teaching.contracts_v2 import LessonBlockV2

        if not isinstance(raw, dict):
            return None
        try:
            block = LessonBlockV2.model_validate(raw)
        except (ValidationError, ValueError, TypeError):
            # A partial or malformed object waits for the complete draft.
            return None
        refs, sources = block.course_criterion_refs, block.source_refs
        if block.block_ref in self.sent or len(set(refs)) != len(refs) or not set(refs) <= self.criterion_refs:
            return None
        if len(set(sources)) != len(sources) or not set(sources) <= self.evidence_refs:
            return None
        if self.source_policy == "strict_docs" and not sources:
            return None
        if self.source_policy == "topic" and sources:
            return None
        if block.synthetic and block.type != "example":
            return None
        if not set(re.findall(r"\[(s\d+)\]", block.text)) <= set(sources):
            return None
        return block

    async def offer(self, raw_blocks):
        from app.services.content_event_service import preview_block_fits

        for raw in raw_blocks:
            block = self._checked(raw)
            if block is None:
                continue
            self.sent.append(block.block_ref)
            if preview_block_fits(block.block_ref, block.text, block.source_refs):
                await self.preview.block(block.block_ref, block.text, block.source_refs)


def _distinct_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_json")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("invalid_json")


class CourseGenerator:
    def __init__(self, outline_llm, lesson_llm, *, timeout_seconds=120, model_configuration=None, reviewer=None):
        self.outline_llm, self.lesson_llm = outline_llm, lesson_llm
        self.timeout_seconds = timeout_seconds
        self.model_configuration = model_configuration or {}
        self.skill = teaching_skill()
        self.reviewer = reviewer

    async def outline(self, spec, material, *, budget):
        return await self._generate("outline", spec, material, budget=budget)

    async def lesson(self, spec, unit, material, *, budget, course_criteria=None):
        return await self._generate("lesson", spec, material, unit=unit, course_criteria=course_criteria, budget=budget)

    async def _generate(self, kind, spec, material, *, unit=None, course_criteria=None, budget):
        feedback_codes = ()
        for attempt in range(2):
            try:
                generated = await self.generate_once(
                    kind, spec, material, unit=unit, course_criteria=course_criteria,
                    feedback_codes=feedback_codes, generation_revision=attempt + 1, budget=budget,
                )
            except TeachingDraftInvalid as exc:
                if attempt:
                    raise AppError(422, "course_generation_invalid", "课程内容未通过基本检查，请重试") from exc
                feedback_codes = exc.codes
                continue
            generated["effective_config"]["generation_attempts"] = attempt + 1
            return generated
        raise AssertionError("Unreachable generation state")

    async def generate_once(
        self, kind: Literal["outline", "lesson"], spec, material, *, unit=None,
        course_criteria: list[CourseCriterionDraft] | None = None,
        feedback_codes: tuple[str, ...] = (), findings=(), generation_revision=1, policy=None, budget,
    ) -> GeneratedTeachingArtifact:
        """Exactly one reservation and transport call. Only the caller may repair."""
        from langchain_core.messages import HumanMessage, SystemMessage

        if kind not in {"outline", "lesson"} or (kind == "lesson" and unit is None):
            raise ValueError("A generation kind and saved lesson unit are required")
        version = V1 if kind == "lesson" and not isinstance(unit, TeachUnitV2) else V2
        data = dict(request=spec.model_dump(mode="json", exclude={"scope"}), **material.prompt_data())
        if unit is not None:
            data["unit"] = unit.model_dump(mode="json", exclude={"source_refs"})
        if version == V2 and kind == "lesson":
            criteria = course_criteria or []
            known = {item.course_criterion_ref: item for item in criteria}
            if len(known) != len(criteria) or not set(unit.course_criterion_refs) <= set(known):
                raise AppError(409, "course_criteria_changed", "课程目标与课时不匹配，请刷新后重试")
            data["course_criteria"] = [known[ref].model_dump(mode="json") for ref in unit.course_criterion_refs]
        elif course_criteria:
            data["frozen_course_criteria"] = [item.model_dump(mode="json") for item in course_criteria]
        if findings:
            data["review_findings"] = [finding.model_dump(mode="json") for finding in findings]
        messages = [
            SystemMessage(content=system_prompt(kind, spec.source_policy, schema_version=version)),
            HumanMessage(content=dump(data)),
        ]
        codes = safe_feedback_codes(feedback_codes)
        if codes:
            messages.append(HumanMessage(content="按相同输入重新生成完整JSON，修正以下检查项：" + ",".join(codes)))
        input_size = 32 + sum(count_tokens(message.content) for message in messages)
        input_limit = policy.repair_input_limit if policy is not None and generation_revision > 1 else INPUT_LIMIT
        if input_size > input_limit:
            raise AppError(422, "course_scope_too_large", "课程输入超出上限，请减少课程目标或资料范围")
        budget.reserve("llm", input_tokens=input_size)
        llm = self.outline_llm if kind == "outline" else self.lesson_llm
        from app.services.provider_meter import MeteredChat

        if isinstance(llm, MeteredChat):
            # New wrapper, same client: concurrent tasks never mutate a shared purpose.
            purpose = "course_teaching_repair" if generation_revision > 1 else "course_" + kind
            llm = MeteredChat(
                llm.llm, purpose=purpose, output_upper=llm.output_upper,
                config_source=llm.config_source, api_key=llm.api_key,
            )
        timeout = policy.repair_timeout_seconds if policy is not None and generation_revision > 1 else self.timeout_seconds
        gate = await self._lesson_preview(kind, version, spec, unit, material, generation_revision)
        if gate is None:
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=min(timeout, budget.remaining_seconds))
        else:
            from app.llm.streaming import JsonContentDecoder

            decoder = JsonContentDecoder()

            async def on_chunk(chunk):
                decoder.feed(chunk)
                await gate.offer(decoder.complete_blocks(container="payload"))

            invoke = (
                llm.ainvoke_streamed(messages, on_chunk=on_chunk)
                if callable(getattr(llm, "ainvoke_streamed", None)) else llm.ainvoke(messages)
            )
            response = await asyncio.wait_for(invoke, timeout=min(timeout, budget.remaining_seconds))
        output_limit = 3000 if kind == "outline" else 4500
        # Record even malformed/truncated responses. No parse failure refunds a call.
        output_method = self._record_output(response, budget, output_limit, unknown_reserve=policy is not None)
        try:
            raw = response_text(response).strip()
        except (ValueError, TypeError, AttributeError) as exc:
            raise AppError(422, "course_generation_incomplete", "模型未返回完整课程内容，请重试") from exc
        try:
            fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            decoded = json.loads(fenced[1] if fenced else raw, object_pairs_hook=_distinct_object, parse_constant=_invalid_constant)
            if not isinstance(decoded, dict):
                raise ValueError("invalid_json")
            if decoded.get("schema_version") != version:
                raise ValueError("unsupported_teach_schema_version")
            # 可视化是可选增强：先降级无效图形，再走原有正文/引用校验。
            decoded, visual_warnings = strip_invalid_visuals(decoded)
            draft = parse_course_draft(decoded) if kind == "outline" else parse_lesson_draft(decoded)
            self._validate(draft, kind, spec, unit, material)
            if kind == "outline" and course_criteria and draft.payload.course_criteria != course_criteria:
                raise ValueError("course_criteria_changed")
        except json.JSONDecodeError:
            raise TeachingDraftInvalid(("invalid_json",)) from None
        except (ValueError, TypeError) as exc:
            # Pydantic's traceback can contain rejected input. Only fixed codes
            # may escape this boundary, including on a final failed repair.
            raise TeachingDraftInvalid(validation_codes(exc)) from None
        for warning in visual_warnings:
            if warning not in draft.warnings:
                draft.warnings.append(warning)
        if spec.source_policy == "topic":
            notice = "课程由模型生成，未进行外部资料核验。"
            if notice not in draft.warnings:
                draft.warnings.append(notice)
        draft.warnings.extend(warning for warning in material.warnings if warning not in draft.warnings)
        if gate is not None:
            # Providers without streaming still show validated blocks once parsed.
            await gate.offer(draft.payload.model_dump(mode="json")["blocks"])
        used = {source.source_ref for source in draft.sources}
        content = draft.model_dump(mode="json")
        return dict(
            draft=content, draft_hash=draft_hash(content),
            evidence={ref: item.model_dump(mode="json") for ref, item in material.evidence.items() if ref in used},
            skill_version=self.skill["version"], skill_hash=self.skill["hash"],
            effective_config={**self.model_configuration, "prompt_version": PROMPT_VERSION,
                              "schema_version": version, "input_limit": input_limit, "output_limit": output_limit,
                              "output_token_count_method": output_method, "generation_attempts": 1},
        )

    @staticmethod
    async def _lesson_preview(kind, version, spec, unit, material, generation_revision):
        """Bind the private preview to this draft; legacy v1 blocks have no stable id."""
        if kind != "lesson" or version != V2:
            return None
        from app.services.content_event_service import reset_current_preview

        preview = await reset_current_preview(generation_revision)
        if preview is None or preview.disabled:
            return None
        return LessonBlockPreview(
            preview, source_policy=spec.source_policy,
            criterion_refs=unit.course_criterion_refs, evidence_refs=material.evidence.keys(),
        )

    @staticmethod
    def _record_output(response, budget, output_limit, *, unknown_reserve=False):
        usage = getattr(response, "usage_metadata", None)
        output = usage.get("output_tokens") if isinstance(usage, dict) else None
        metadata = getattr(response, "response_metadata", None)
        invalid_usage = output is not None and (type(output) is not int or output < 0)
        if type(output) is not int or output < 0:
            legacy = metadata.get("token_usage", {}) if isinstance(metadata, dict) else {}
            output = legacy.get("completion_tokens") if isinstance(legacy, dict) else None
        if type(output) is int and output >= 0:
            method = "provider-reported"
        elif unknown_reserve:
            output, method = output_limit, "configured-output-reserve-v1"
        else:
            content = getattr(response, "content", "")
            output = max(1, count_tokens(content if isinstance(content, str) else dump(content)))
            method = "utf8-upper-bound-v1"
        budget.record_output(output)
        if invalid_usage:
            raise AppError(422, "course_generation_invalid_usage", "模型用量信息无效，请重试")
        if output > output_limit:
            raise BudgetExceeded("Course output limit exceeded")
        return method

    @staticmethod
    def _validate(draft, kind, spec, unit, material):
        if draft.source_policy != spec.source_policy or any(v is not None for v in draft.context.model_dump().values()):
            raise ValueError("source_policy_or_context_changed")
        known = {s.source_ref: s for s in material.sources}
        for source in draft.sources:
            if source.source_ref not in known or source != known[source.source_ref]:
                raise ValueError("source_not_from_material")
        if kind == "lesson" and spec.source_policy == "strict_docs" and draft.status in {"needs_sources", "insufficient_evidence"}:
            raise AppError(422, "course_material_gap", "当前资料不足以支持本课目标")
        if draft.payload is None:
            if draft.status in {"needs_sources", "insufficient_evidence"} and spec.source_policy == "strict_docs":
                raise AppError(422, "course_material_gap", "当前资料不足以支持课程目标")
            raise ValueError("missing_generated_content")
        if kind == "outline":
            if len(draft.payload.units) != spec.lesson_count:
                raise ValueError("wrong_lesson_count")
            for item in draft.payload.units:
                if item.estimated_minutes and item.estimated_minutes > spec.daily_minutes:
                    raise ValueError("lesson_duration_exceeds_study_time")
                if any(c.concept_id for c in item.concepts):
                    raise ValueError("invented_concept_identity")
                if spec.source_policy == "topic" and item.availability != "ready":
                    raise ValueError("topic_unit_material_gap")
        else:
            if any(getattr(draft.payload, field) != getattr(unit, field) for field in ("unit_ref", "title", "objective", "estimated_minutes")):
                raise ValueError("lesson_outline_mismatch")
            if not {"explanation", "example", "recap"} <= {b.type for b in draft.payload.blocks}:
                raise ValueError("lesson_needs_explanation_example_recap")
            if not draft.payload.checks:
                raise ValueError("lesson_needs_self_check")
            if draft.schema_version == V2:
                require_lesson_alignment(draft.payload, unit)
