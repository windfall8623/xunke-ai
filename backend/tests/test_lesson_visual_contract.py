"""Safe lesson visuals: structural contracts and graceful degradation (B04)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.teaching.contracts import (
    VISUAL_UNAVAILABLE_WARNING,
    FlowVisual,
    LessonBlock,
    LessonVisual,
    StepsVisual,
    strip_invalid_visuals,
)

_visual = TypeAdapter(LessonVisual)


def visual_block(visual):
    return {
        "type": "explanation", "text": "正文说明。", "source_refs": [],
        "synthetic": False, "visual": visual,
    }


def test_valid_flow_and_steps_visuals_pass():
    flow = {
        "kind": "flow", "title": "调用流程",
        "steps": [{"label": "传入参数"}, {"label": "执行函数", "detail": "计算并返回"}],
        "fallback_text": "先传参，再执行，最后拿到返回值。",
    }
    validated = FlowVisual.model_validate(flow)
    assert validated.steps[1].detail == "计算并返回"
    block = LessonBlock.model_validate(visual_block(flow))
    assert block.visual is not None


def test_comparison_row_width_mismatch_is_rejected():
    broken = {
        "kind": "comparison", "title": "对比",
        "columns": ["值类型", "引用类型"], "rows": [["直接存值"]],
        "fallback_text": "值类型直接存值；引用类型存地址。",
    }
    with pytest.raises(ValidationError):
        _visual.validate_python(broken)


def test_visual_rejects_unknown_fields_and_html_ish_payloads():
    with pytest.raises(ValidationError):
        LessonBlock.model_validate(visual_block({
            "kind": "steps", "title": "步骤", "steps": [{"label": "x"}],
            "fallback_text": "说明", "html": "<script>alert(1)</script>",
        }))
    with pytest.raises(ValidationError):
        _visual.validate_python({"kind": "svg", "title": "x", "body": "<svg/>"})


def test_strip_invalid_visuals_degrades_without_touching_the_text():
    good = {
        "kind": "steps", "title": "步骤", "steps": [{"label": "第一步"}],
        "fallback_text": "按第一步执行。",
    }
    document = {
        "payload": {"blocks": [visual_block(good), visual_block({"kind": "nope"})]},
        "warnings": [],
    }
    stripped, warnings = strip_invalid_visuals(document)
    assert stripped["payload"]["blocks"][0]["visual"]["kind"] == "steps"
    assert "visual" not in stripped["payload"]["blocks"][1]
    assert warnings == [VISUAL_UNAVAILABLE_WARNING]
    # 正文原样保留：图形降级不能掩盖内容错误。
    assert stripped["payload"]["blocks"][1]["text"] == "正文说明。"


def test_old_blocks_without_visual_stay_readable():
    block = LessonBlock.model_validate({
        "type": "recap", "text": "旧正文。", "source_refs": [], "synthetic": False,
    })
    assert block.visual is None
