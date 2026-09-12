# 课程草案输出格式 v1

在调用方要求 JSON、保存课程草案或交给课程适配器处理时读取。默认教学对话使用自然语言，不向学习者暴露这些协议字段。

此格式是教学内容的结构化草案协议。循课后端已用严格的 `CourseDraft` / `LessonDraft` 校验课程与课时草案，由 Course 服务分配身份、保存版本并投影为 `CourseView` / `CourseLessonView` 等 HTTP DTO。草案仍不是创建课程或生成课时的 HTTP 请求，调用接口应使用对应的 `CourseCreate`、`CourseLessonGenerate` 等输入契约；今日学习建议与反馈草案也不代表已有同名接口。实际接入边界见 [project-integration.md](project-integration.md)。

## 通用信封

结构化输出为一个 JSON 对象，不附加 Markdown 围栏。一次对象针对一门课程及一种来源策略；多个独立课程分别生成对象，不混合其资料与进度。

| 字段 | 类型与含义 |
| --- | --- |
| `schema_version` | 固定字符串 `xunke-teach.v1` |
| `kind` | `course_draft`、`lesson_draft`、`study_plan_draft` 或 `feedback_draft` |
| `source_policy` | `strict_docs` 或 `topic` |
| `status` | `draft`、`needs_input`、`needs_sources` 或 `insufficient_evidence` |
| `context` | 含 `space_id`、`course_id`、`scope_revision`；已有值原样保留，未知值为 `null` |
| `assumptions` | 字符串数组，记录采用的可调整假设 |
| `warnings` | 字符串数组，记录来源、范围或时效限制 |
| `questions` | 待补充信息的问题数组；没有问题时为 `[]` |
| `sources` | 本次实际可用来源的数组 |
| `payload` | 对应类型的草案；信息或资料完全不足时为 `null` |

`draft` 表示内容草案已生成，不表示它已保存、发布、通过正式评测或被用户完成。不要输出未经服务端确认的成功回执。

- `needs_input`：无法确定主题、目标或续学对象，需要用户补充。
- `needs_sources`：用户要求基于资料，但材料无法读取、缺少授权或来源已失效。`payload=null`，不退回纯 LLM 教学。
- `insufficient_evidence`：资料可以读取，但不足以支撑全部目标。可以交付有依据的部分，并标明缺口；不得把未覆盖部分伪装成完整课程。

## 来源与局部引用

每个来源对象使用以下字段：

| 字段 | 规则 |
| --- | --- |
| `source_ref` | 当前草案内唯一的引用名，例如 `input-1`；它不是数据库 ID |
| `kind` | `provided_material` 或 `rag_evidence` |
| `title` | 用户给定或工具实际返回的标题；没有标题时使用“本次提供材料”等诚实描述 |
| `locator` | 实际页码、章节或段落位置；未知为 `null` |
| `evidence_id` | 仅复制真实检索结果中的值；直接阅读材料时为 `null` |
| `document_version_id` | 已知的真实资料版本；否则为 `null` |

直接阅读材料时可以创建局部 `source_ref` 来引用实际段落，但不能由此伪造项目的文档或证据身份。资料权限和引用支持关系仍需要宿主校验。

`strict_docs` 中已经生成的核心知识单元及事实性内容块应具有有效 `source_refs`，且指向 `sources` 中的实际材料。仅写文件名而没有支持内容不算有效依据。

`topic` 中 `sources=[]`，所有 `source_refs=[]`，并在 `warnings` 中标明模型生成且未外部核验。模型回忆起某篇文章，也不能填入来源表。

当前协议不包含自动联网增强。用户要求补充外部资料时，由实际可用且获授权的资料收集流程获取；将可读取材料与来源范围交给下一次资料模式生成。不能在纯 LLM 请求中偷偷执行联网。

## `course_draft.payload`

| 字段 | 含义 |
| --- | --- |
| `title` | 课程名称 |
| `mission` | 对象：`goal`、`prior_knowledge`、`success_criteria`、`daily_minutes`、`deadline` |
| `units` | 按建议学习顺序排列的单元数组 |

`mission.prior_knowledge` 与 `success_criteria` 是字符串数组；`daily_minutes` 是正整数或 `null`，`deadline` 为已提供的日期或 `null`。自述基础应注明来自用户自述。

每个单元包含：

- `unit_ref`：当前课程内的局部引用，不使用虚构的服务端 `unit_id`。
- `title`、`objective`：名称与本课可观察的目标；缺资料且尚不能确定目标时，`objective` 为 `null`。
- `concepts`：`concept_ref`、`title` 对象数组；已存在的概念可另带真实 `concept_id`。
- `prerequisite_unit_refs`：前置单元引用数组，只引用课程中已有单元，不成环；`[]` 表示已确定没有课程内前置单元，缺资料且前置关系未知时为 `null`。课程外的基础写入 `mission.prior_knowledge` 并注明是否已确认。
- `estimated_minutes`：正整数估计，不表示实际耗时；缺资料且无法估计时为 `null`。
- `source_refs`：对应来源。
- `availability`：`ready` 或 `material_gap`；资料模式的未支持单元只能标为后者。
- `completion_check`：建议如何检查本课目标，不直接生成完成状态；缺资料且无法设计时为 `null`。

`availability=ready` 的单元须给出明确目标、前置数组、正整数时长与检查方式。`material_gap` 单元允许上述待定字段为 `null`，`concepts` 也可为 `[]`；只保留用户提出或材料支持的范围占位，不为满足字段格式编造知识、前置关系或课时。待资料补齐后再完善，不能将占位单元纳入可立即执行的今日任务。

可直接解析的主题模式示例；局部引用仅代表这份新草案：

```json
{
  "schema_version": "xunke-teach.v1",
  "kind": "course_draft",
  "source_policy": "topic",
  "status": "draft",
  "context": {"space_id": null, "course_id": null, "scope_revision": null},
  "assumptions": ["按一次约 20 分钟安排，可根据反馈调整"],
  "warnings": ["课程由模型生成，未进行外部资料核验"],
  "questions": [],
  "sources": [],
  "payload": {
    "title": "Python 函数入门",
    "mission": {
      "goal": "能够编写带参数和返回值的函数",
      "prior_knowledge": ["用户自述了解变量和基本运算"],
      "success_criteria": ["独立编写函数并解释参数与返回值的作用"],
      "daily_minutes": 20,
      "deadline": null
    },
    "units": [
      {
        "unit_ref": "unit-1",
        "title": "参数与返回值",
        "objective": "用函数接收两个数并返回计算结果",
        "concepts": [{"concept_ref": "concept-1", "title": "函数输入与输出"}],
        "prerequisite_unit_refs": [],
        "estimated_minutes": 20,
        "source_refs": [],
        "availability": "ready",
        "completion_check": "编写一个新函数，并解释 return 与 print 的区别"
      }
    ]
  }
}
```

## `lesson_draft.payload`

- `unit_ref`、`title`、`objective`、`estimated_minutes`：对应已有纲要的单元。
- `blocks`：内容块数组。每块含 `type`（`explanation`、`example`、`reference`、`recap`）、`text`、`source_refs`；构造的示例增加 `synthetic=true`。
- `checks`：检查题数组，含局部 `check_ref`、`question_type`、`prompt`；选择题可附选项。它们是教学草案，不是现有题目接口的完整请求。
- `next_step`：完成本次检查后的建议，不预判学习者将答对。

面向学习者的课程内容不包含未作答题目的标准答案、隐藏评分要点或其他用户记录。生产题目的私有答案和评分细则由现有题目生成与评分服务管理。

实际创建练习需要把草案映射到当前接口，并检查 3–10 题、支持的题型、概念、资料及权限等约束。对话中的一道检查题不等于已经创建站内练习。

## `study_plan_draft.payload`

- `planning_date`、`timezone`：来自用户或宿主的可靠当前时间；仅安排下一次学习且日期未知时可为 `null`。
- `available_minutes`：本次可用时间。
- `tasks`：任务数组，每项含 `type`（`learn`、`continue`、`practice`、`review`）、`unit_ref`（无对应单元时为 `null`）、`concept_refs`、`estimated_minutes`、`reason`、`completion_check`。
- 有真实复习任务时，可以原样附上 `review_task_id` 和服务端返回的时间；不能自行创建正式复习身份或改写其到期时间。

任务预计时间之和不超过本次可用时间。资料不足、上下文缺失或暂停的活动不能被描述成可立即执行的正常学习任务。时间紧张时给一个明确的核心任务，其余作为后续建议。

## `feedback_draft.payload`

- `unit_ref`、`check_ref`：指向本次实际发生的教学检查；无法定位时为 `null`。
- `basis`：`observed_response`、`self_report`、`confirmed_assessment` 或 `provisional_assessment`，与实际输入一致。
- `what_went_well`、`gaps`、`hypotheses`：分别保存观察到的有效部分、缺失与待确认的错因。
- `explanation`、`source_refs`：本次教学解释及其依据。
- `next_check`：需要继续确认理解时给一个问题，否则为 `null`。
- `next_action`：建议继续、补讲或复习，并说明理由。

此类输出只表达教学反馈。不得包含模型自行生成的正式分数、确认回执、`stage`、`due_at` 或 `independent_eligible` 更新；正式评分数据仍由原服务维护。

## 接入方需要验证的语义

JSON 可解析不代表课程正确。接入时还要核对来源引用确实存在且支持正文、单元前置关系无环、概念与练习范围一致、计划时长合理，以及用户与资料权限仍有效。

保存时由服务端分配身份、版本和幂等键，并映射局部引用。不要把模型自检当作已经完成这些验证。
