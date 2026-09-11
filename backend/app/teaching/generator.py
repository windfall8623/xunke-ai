"""One generation and at most one schema repair, both metered and deadline-bound."""

import asyncio
import json
import re

from pydantic import ValidationError

from app.core.errors import AppError
from app.core.values import dump
from app.llm.responses import response_text
from app.rag.budget import count_tokens
from app.teaching.contracts import CourseDraft, LessonDraft
from app.teaching.prompts import INPUT_LIMIT, PROMPT_VERSION, system_prompt, teaching_skill


class CourseGenerator:
    def __init__(self, outline_llm, lesson_llm, *, timeout_seconds=120, model_configuration=None):
        self.outline_llm, self.lesson_llm = outline_llm, lesson_llm
        self.timeout_seconds = timeout_seconds
        self.model_configuration = model_configuration or {}
        self.skill = teaching_skill()

    async def outline(self, spec, material, *, budget):
        return await self._generate("outline", spec, material, budget=budget)

    async def lesson(self, spec, unit, material, *, budget):
        return await self._generate("lesson", spec, material, unit=unit, budget=budget)

    async def _generate(self, kind, spec, material, *, unit=None, budget):
        from langchain_core.messages import HumanMessage, SystemMessage

        data = dict(request=spec.model_dump(mode="json", exclude={"scope"}), **material.prompt_data())
        if unit is not None:
            data["unit"] = unit.model_dump(mode="json", exclude={"source_refs"})
        messages = [SystemMessage(content=system_prompt(kind, spec.source_policy)), HumanMessage(content=dump(data))]
        llm = self.outline_llm if kind == "outline" else self.lesson_llm
        expected = CourseDraft if kind == "outline" else LessonDraft
        for attempt in range(2):
            input_size = 32 + sum(count_tokens(m.content) for m in messages)
            if input_size > INPUT_LIMIT:
                raise AppError(422, "course_scope_too_large", "课程输入超出上限，请减少课程目标或资料范围")
            budget.reserve("llm", input_tokens=input_size)
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=min(self.timeout_seconds, budget.remaining_seconds))
            try:
                raw = response_text(response).strip()
                fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
                draft = expected.model_validate(json.loads(fenced[1] if fenced else raw))
                self._validate(draft, kind, spec, unit, material)
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if attempt:
                    raise AppError(422, "course_generation_invalid", "模型返回的课程格式不完整，请重试") from exc
                # A repair gets the same bounded source input and sanitized field errors.
                # Never send a potentially huge malformed model response back verbatim.
                fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()[:6]] if isinstance(exc, ValidationError) else ["references_or_content"]
                messages.append(HumanMessage(content="上一稿未通过结构校验。请按相同输入重新生成完整JSON，仅修复字段格式、引用或单元约束：" + ",".join(fields)))
                continue
            draft.context.course_id = None
            if spec.source_policy == "topic":
                notice = "课程由模型生成，未进行外部资料核验。"
                if notice not in draft.warnings:
                    draft.warnings.append(notice)
            draft.warnings.extend(w for w in material.warnings if w not in draft.warnings)
            used = {s.source_ref for s in draft.sources}
            return dict(
                draft=draft.model_dump(mode="json"),
                evidence={ref: item.model_dump(mode="json") for ref, item in material.evidence.items() if ref in used},
                skill_version=self.skill["version"], skill_hash=self.skill["hash"],
                effective_config={**self.model_configuration, "prompt_version": PROMPT_VERSION,
                                  "input_limit": INPUT_LIMIT, "output_limit": 3000 if kind == "outline" else 4500,
                                  "generation_attempts": attempt + 1},
            )
        raise AssertionError("Unreachable generation state")

    @staticmethod
    def _validate(draft, kind, spec, unit, material):
        if draft.source_policy != spec.source_policy or any(v is not None for v in draft.context.model_dump().values()):
            raise ValueError("Model changed source mode or invented persistence identity")
        known = {s.source_ref: s for s in material.sources}
        for source in draft.sources:
            if source.source_ref not in known or source != known[source.source_ref]:
                raise ValueError("A source must be copied from actual evidence")
        if draft.payload is None:
            if draft.status == "insufficient_evidence" and spec.source_policy == "strict_docs":
                raise AppError(422, "course_material_gap", "当前资料不足以支持课程目标")
            raise ValueError("Missing generated content")
        if kind == "outline":
            if len(draft.payload.units) != spec.lesson_count:
                raise ValueError("Wrong lesson count")
            for item in draft.payload.units:
                if item.estimated_minutes and item.estimated_minutes > spec.daily_minutes:
                    raise ValueError("Lesson duration exceeds study time")
                if any(c.concept_id for c in item.concepts):
                    raise ValueError("Course concepts cannot invent database IDs")
                if spec.source_policy == "topic" and item.availability != "ready":
                    raise ValueError("Topic courses cannot require missing documents")
        else:
            if any(getattr(draft.payload, field) != getattr(unit, field) for field in ("unit_ref", "title", "objective", "estimated_minutes")):
                raise ValueError("Lesson must follow its saved outline")
            if not {"explanation", "example", "recap"} <= {b.type for b in draft.payload.blocks}:
                raise ValueError("Lesson needs explanation, example and recap")
            if not draft.payload.checks:
                raise ValueError("Lesson needs a self check")
