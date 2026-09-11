# 智学项目适配参考

本参考依据当前仓库代码区分现有能力与拟议设计；技能文件本身不会注册后端接口、连接数据库或增加 React 页面。
在聊天或 CLI 中即可使用教学流程。只有会话实际接入并获授权的项目工具，才可执行相应应用操作。

## 教学输入输出与现有能力

| 教学信息 | 可复用的项目承载 | 映射边界 |
| --- | --- | --- |
| 学习主题、目标与时间预算 | 学习空间、`StudyGoal` | 目标文字可映射；每日时长与截止日只是计划属性。 |
| 资料清单、章节与事实依据 | `RequestedScope`、冻结的 `scope_revision`、QA 事实块 | 引用必须指向实际可访问的资料及其版本。 |
| 课程单元与概念顺序 | `StudyUnit`、`StudyConcept` | 可表达单元位置和概念；当前没有完整课程讲义或逐课教学状态契约。 |
| 单选、多选、判断检查 | 旧 `QuizSpec` / `QuizArtifact` | 支持 `topic`、`strict_docs`、`doc_plus_web`；不要把这些题型塞入新 practice。 |
| 填空、数值、简答检查 | `PracticeSpec` 与公开 practice 视图 | 必须关联现有空间、资料范围版本与概念。 |
| 作答、反馈、学习记录 | attempt、assessment、completion 与学习事件 | 保留真实作答及评分状态，聊天总结不等于服务端学习事实。 |
| 学习概览与续学入口 | 现有 React 学习空间、练习、学习记录页面 | 可作为未来展示位置；本技能未向这些页面接入课程。 |

入口依据：[学习 DTO](../../../../backend/app/models/study.py)、[旧题目契约](../../../../backend/app/rag/contracts.py)、[新练习契约](../../../../backend/app/practice/contracts.py)。
页面依据：[学习空间](../../../../web/src/pages/study/StudySpacePage.tsx)、[练习页](../../../../web/src/pages/PracticePage.tsx)、[学习记录](../../../../web/src/pages/study/LearningRecordsPage.tsx)。

## 两种课程模式

`strict_docs`：使用用户授权的资料与检索证据，由 LLM 组织教学、例子和问题；关键知识点附可核对的来源。
检索或资料不足时说明缺口，缩小本课范围；不能用模型常识补齐后再标成资料结论。
若 CLI 只能读取用户提供的原文或摘录，就如实标明依据；没有完成项目 RAG 调用时，不声称已检索知识库。

`topic`：没有资料时，依用户主题与先修水平使用 LLM 知识组织课程；标明模型知识来源，资料引用留空。
旧客观题流程已有 `topic` 能力，但无资料课程不能据此直接创建现有 StudySpace 或新 practice。
这类课程仍可完整地在聊天中规划、授课与反馈，应用内持久化映射保持草稿。

两种模式默认均不联网。旧接口存在 `doc_plus_web` 不代表技能可自动开启搜索或扩展用户选定的资料范围。

## 已核对的接口限制

1. `StudySpaceCreate` 必须在 `scope` 与 `answer_id` 中恰选一个；不能二者都空，也不能同时提供。
2. `RequestedScope.documents` 要求 1–5 份资料；空文档数组不是合法的无资料空间。`StudyUnitCreate` 同样要求 `scope` 与 `scope_revision`。
3. `PracticeSpec` 只有 `cloze`、`numeric`、`short_answer` 三种题型；没有 `unit_id` 或 `source_policy`。目标与概念须一一对应，每批 1–3 个目标、3–10 道题。
4. from-QA 入口生成旧客观题并固定 `strict_docs`；公开请求没有 `unit_id`，授权逻辑还会显式拒绝注入的单元关联。
5. 目标的 `daily_minutes`、`deadline` 当前用于存储、更新和展示；没有依据这两个字段拆分课程、安排每日课时或自动授课的调度器。

核对位置：[空间与单元 DTO](../../../../backend/app/models/study.py)、[资料范围](../../../../backend/app/rag/contracts.py)、[PracticeSpec](../../../../backend/app/practice/contracts.py)、[from-QA 服务](../../../../backend/app/services/learning_quiz_service.py)、[目标 CRUD](../../../../backend/app/services/learning_space_service.py)。

## 评分与复习事实的边界

- 区分作答内容、教学反馈、自评和正式评分；“我懂了”可以记录为自评，不能提升掌握阶段。
- 保留 `confirmed` 与 `provisional`。模型给出分数不意味着评分已确认；确认状态须来自现有评分或复核流程。
- 简答自动评分只有满足现有校准与核验条件才可能确认；不确定结果保留 `needs_review`，技能不能自行改为确认。
- `independent_eligible` 由服务端证据规则产生；确认评分与 `help_usage="none"` 是必要条件，不由模型主观判断代替。
- 自评的 `independent_eligible` 固定为 `false`；使用提示、看过答案或帮助情况未知时，不得伪报独立作答。
- 作答和评分通过现有服务维护；保留当前评分与历史评分、确认与暂定结果的区别，不把聊天摘要写成已经完成的事件。
- `stage` 和 `due_at` 由现有复习规则及其投影维护，LLM 仅能给教学建议，不能直接覆盖状态。
- 现有规则处理确认错误或部分得分、受帮助作答、同日重复及重复题目版本；阶段为 0–4，独立成功对应 1/3/7/14 天间隔。
- 用户明确调整复习日期时，应由既有复习操作处理版本校验与人工覆盖；技能不得暗中把建议时间写入 `due_at`。

依据：[公开评分与自评视图](../../../../backend/app/models/practice.py)、[简答评分规则](../../../../backend/app/practice/short_answer.py)、[复习规则](../../../../backend/app/learning/review_rules.py)、[学习事件服务](../../../../backend/app/services/learning_event_service.py)、[复习请求 DTO](../../../../backend/app/models/study.py)。

## 资料授权与版本

资料权限、空间归属和范围版本由服务端校验，技能不能从标题猜测文档 ID、替换范围版本或跨空间拼接概念。
收到 `source_revoked`、`source_status="revoked"` 或明确的权限撤销结果时，停止依赖该资料的生成、呈现和评分。
不得继续使用缓存摘录，不得把原任务悄悄降级为 `topic`；待用户重新选择可访问资料后，再建立合法的来源上下文。
资料不足、工具不可用和权限撤销须分别说明；任何一种情况都不能伪造引用或报告调用成功。
依据：[资料范围授权服务](../../../../backend/app/services/learning_scope_service.py)、[新练习依赖校验](../../../../backend/app/services/practice_service.py)。

## 未来适配的最小边界（proposed，尚未实现）

下面是未来开发时的数据与职责建议，不是可调用工具、现有 API 或已实施的数据库结构。

1. **课程草稿容器**：承载主题、模式、先修条件、可观察目标、单元顺序、时间预算及来源说明；与已有学习空间建立经授权验证的可选关联。
2. **单课内容与进度**：保存讲解块、练习意图、理解检查、教学反馈及续学摘要；课程序号与真实 `unit_id` 分开绑定。
3. **来源适配**：`strict_docs` 沿用资料授权与冻结版本；`topic` 需要独立的无资料课程承载，不能用空 `RequestedScope` 绕过现有校验。
4. **练习适配**：分别映射旧客观题和新 practice。若要支持单元绑定或 topic 新题型，另行设计契约、授权及来源规则，不能向当前请求添加不存在的字段。
5. **记录与展示适配**：课程内容可由 React 渲染，学习事实继续走既有作答、评分、事件与复习服务；保存成功与任务完成分别依据真实回执。

这些边界足以指导后续接入；用户无需先实现它们，便可使用当前技能进行聊天式学习。

## 未接入工具时的执行方式

- 输出课程、单课、练习意图和续学记录的 `draft`；清楚标明尚未保存到智学项目。
- 用顺序编号或“待绑定”表达课程关联；真实 `space_id`、`unit_id`、`concept_id`、`attempt_id` 等只采用可信输入或工具返回值。
- 不写 SQL、不直接改数据库、不自行构造服务调用成功的回执，也不把聊天输出描述成新增了空间、题目或复习任务。
- 知识库资料仅在应用内可见而当前没有访问工具时，产出待资料的草稿并说明缺少的内容，不伪装完成 RAG。
- 原版 teach 的 `MISSION`、`RESOURCES`、本地学习记录与 HTML 看板在这里分别对应目标、来源、续学摘要和可选展示；它们不再是使用技能前必须创建的文件。
- 用户另行要求导出时才生成相应文件；导出文件仍不代表应用持久化或 React 集成完成。
