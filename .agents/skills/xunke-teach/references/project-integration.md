# 循课项目适配参考

本参考依据当前仓库中的 Course 链路说明已接入能力及调用边界。网站通过固定教学规范、严格草案校验和课程服务生成内容，并保存课程、课时和练习关联；服务器不运行 Codex，也不执行技能中的终端或文件操作。
在聊天或 CLI 中仍可独立使用教学流程。项目已经实现课程功能，不等于当前会话已经连接项目工具；只有实际接入并获授权的工具，才可执行相应应用操作。

## 教学输入输出与现有能力

| 教学信息 | 当前项目承载 | 映射边界 |
| --- | --- | --- |
| 学习主题、目标与每日时长 | `CourseCreate`、`learning_courses` | Course 独立承载课程；学习空间的 `StudyGoal` 继续使用原契约。 |
| 资料清单、章节与事实依据 | 课程冻结的 `RequestedScope` / `ResolvedScope`、来源指纹与证据 | 引用必须指向实际可访问的资料及其版本；课程 revision 不替代学习空间 scope_revision。 |
| 课程单元、正文与阅读事实 | `learning_course_lessons`、`CourseLessonView` | 保存纲要单元、讲解、示例、自检与阅读状态；lesson_id 不等于学习空间 unit_id。 |
| 课内补讲、举例、提示与自检反馈 | `CourseTutorCreate`、`learning_course_tutor_turns` 与自检作答 | explain/example/hint/check 仅提供教学帮助；自检反馈不生成正式分数或掌握事实。 |
| 课后三题客观检查 | `QuizSpec` / `QuizArtifact`、`learning_course_quiz_links` | 固定 3 题，使用单选、多选、判断；关联表连接首次检查和补练任务。 |
| 填空、数值、短解释检查 | `PracticeSpec` 与公开 practice 视图 | 沿用学习空间、资料范围版本与概念要求，当前 Course 检查走客观题流程。 |
| 作答与结算 | `quiz_answers`、`quiz_sessions` 及原规则判分服务 | Course 读取真实逐题答案和结算状态；聊天总结不等于服务端学习事实。 |
| 学情与下一步 | `CourseProgressView`、课程页面及原练习与报告页 | 分别展示阅读、首次检查、各次补练与本次错题，按记录推荐后续操作。 |

契约依据：[课程 HTTP DTO](../../../../backend/app/models/course.py)、[教学草案](../../../../backend/app/teaching/contracts.py)、[题目契约](../../../../backend/app/rag/contracts.py)、[综合练习契约](../../../../backend/app/practice/contracts.py)。
页面依据：[课程入口](../../../../web/src/features/courses/CourseListSection.tsx)、[课时内容](../../../../web/src/features/courses/CourseLesson.tsx)、[课程学情](../../../../web/src/features/courses/CourseProgress.tsx)。

## 两种课程模式

`strict_docs`：使用用户授权的资料与检索证据，由 LLM 组织教学、例子和问题；关键知识点附可核对的来源。
网站课程冻结所选资料及章节版本。纲要使用所选目录与真实代表片段，课时按自己的目标检索；目录或少量摘录不代表整份资料已经逐句核验。检索或资料不足时说明缺口，缩小本课范围；不能用模型常识补齐后再标成资料结论。
若 CLI 只能读取用户提供的原文或摘录，就如实标明依据；没有完成项目 RAG 调用时，不声称已检索知识库。

`topic`：没有资料时，依用户主题与先修水平使用 LLM 知识组织课程；标明模型知识来源，资料引用留空。
网站已通过独立 Course 存储主题课程，课程生成不调用 Embedding、RAG 或联网搜索。HTTP 资料 scope 为 null，内部任务使用 owner 正确且 documents 为空的 `ResolvedScope`；不能据此向 StudySpace 或新 practice 传入空资料。

课程只支持上述两种模式，均不自动联网。独立题目接口存在 `doc_plus_web` 不代表课程可以自动开启搜索或扩展用户选定的资料范围。

## 已核对的接口限制

1. `StudySpaceCreate` 必须在 `scope` 与 `answer_id` 中恰选一个；不能二者都空，也不能同时提供。
2. `RequestedScope.documents` 要求 1–5 份资料；空文档数组不是合法的无资料空间。`StudyUnitCreate` 同样要求 `scope` 与 `scope_revision`。
3. `PracticeSpec` 只有 `cloze`、`numeric`、`short_answer` 三种题型；没有 `unit_id` 或 `source_policy`。目标与概念须一一对应，每批 1–3 个目标、3–10 道题。
4. from-QA 入口生成旧客观题并固定 `strict_docs`；公开请求没有 `unit_id`，授权逻辑还会显式拒绝注入的单元关联。
5. 学习空间目标的 `daily_minutes`、`deadline` 仍是目标属性。Course 的 `daily_minutes` 用于约束纲要中的单课时长；下一步由阅读和练习记录给出建议，不是按日期自动排课或自动授课的调度器。
6. Course 创建默认 6 节、每天 20 分钟，允许 1–10 节、每天 5–120 分钟；当前输入不含截止日期。开始生成课时前可修改课程名和课时标题，不能借该操作更换资料范围或任意改写正文。
7. 网站课程接口已有 explain/example/hint/check 四种课内助教模式，支持基于所选内容块提问、提示以及已保存自检回答的教学反馈。助教绑定当前课时内容版本与授权来源；这些回答不进入正式 practice/quiz 评分链。

核对位置：[课程 DTO](../../../../backend/app/models/course.py)、[课程服务](../../../../backend/app/services/course_service.py)、[空间与单元 DTO](../../../../backend/app/models/study.py)、[PracticeSpec](../../../../backend/app/practice/contracts.py)、[from-QA 服务](../../../../backend/app/services/learning_quiz_service.py)。

## 评分与复习事实的边界

- Course 以 read_at 表达阅读事实，以原客观题答案与结算记录表达本次练习表现；首次检查与补练分别统计，不合并为掌握率。课程已读操作与统计查询不写 stage、due_at 或 independent_eligible。
- 区分作答内容、教学反馈、自评和正式评分；“我懂了”可以记录为自评，不能提升掌握阶段。
- 保留 `confirmed` 与 `provisional`。模型给出分数不意味着评分已确认；确认状态须来自现有评分或复核流程。
- 短解释自动评分只有满足现有校准与核验条件才可能确认；不确定结果保留 `needs_review`，技能不能自行改为确认。
- `independent_eligible` 由服务端证据规则产生；确认评分与 `help_usage="none"` 是必要条件，不由模型主观判断代替。
- 自评的 `independent_eligible` 固定为 `false`；使用提示、看过答案或帮助情况未知时，不得伪报独立作答。
- 作答和评分通过现有服务维护；保留当前评分与历史评分、确认与暂定结果的区别，不把聊天摘要写成已经完成的事件。
- `stage` 和 `due_at` 由现有复习规则及其投影维护，LLM 仅能给教学建议，不能直接覆盖状态。
- 现有规则处理确认错误或部分得分、受帮助作答、同日重复及重复题目版本；阶段为 0–4，独立成功对应 1/3/7/14 天间隔。
- 用户明确调整复习日期时，应由既有复习操作处理版本校验与人工覆盖；技能不得暗中把建议时间写入 `due_at`。

依据：[公开评分与自评视图](../../../../backend/app/models/practice.py)、[短解释评分规则](../../../../backend/app/practice/short_answer.py)、[复习规则](../../../../backend/app/learning/review_rules.py)、[学习事件服务](../../../../backend/app/services/learning_event_service.py)、[复习请求 DTO](../../../../backend/app/models/study.py)。

## 资料授权与版本

资料权限、课程或空间归属和范围版本由服务端校验，技能不能从标题猜测文档 ID、替换范围版本或跨空间拼接概念。Course 展示、证据查看、模型调用前与发布时重新授权；对外只投影公开来源字段，不暴露服务器存储路径。
收到 `source_revoked`、`source_status="revoked"` 或明确的权限撤销结果时，停止依赖该资料的生成、呈现和评分。
不得继续使用缓存摘录，不得把原任务悄悄降级为 `topic`；待用户重新选择可访问资料后，再建立合法的来源上下文。
资料不足、工具不可用和权限撤销须分别说明；任何一种情况都不能伪造引用或报告调用成功。
依据：[课程读取与授权](../../../../backend/app/services/course_read.py)、[课程任务发布](../../../../backend/app/workers/course_job.py)、[资料范围授权服务](../../../../backend/app/services/learning_scope_service.py)。

## 已接入的 Course 链路

网站主流程为：**创建课程 → 生成纲要 → 按需生成一节正文 → 阅读与自检 → 三题检查 → 查看学情与错题补练**。

1. **结构化生成与存储**：新纲要及已映射课时使用 `CourseDraftV2` / `LessonDraftV2`，历史 `CourseDraft` / `LessonDraft` 继续按 v1 读取。应用分配真实身份，将课程和课时分别存入 `learning_courses`、`learning_course_lessons`，再显式投影为课程 HTTP DTO。来源模式、资料指纹、内容版本、技能版本和全技能哈希保存在服务端。
2. **按需任务**：一次只生成纲要或一节课。请求沿用任务队列、幂等键、计费和预算约束；已成功的正文直接读取，失败或取消的生成可显式重试。正文包含讲解、示例、小结和不带答案的自检。
3. **练习关联**：每组固定 3 题，复用原出题、逐题提交、规则判分及报告。`learning_course_quiz_links` 同事务关联已存在的 task_id，任务完成且题目发布后才公开 quiz_id；补练引用本课已结算的真实错题，保留首次与历次补练关联。
4. **学情建议**：分别计算已生成、已读、完成首次检查的课时数，以及首次答题表现和各次补练结果。未完成练习优先继续，未补练错题提示回看课时，随后建议学习或检查下一课；不把阅读、正确率或辅助作答写成长期掌握状态。

环境模板提供三个课程配置项：

| 配置 | 作用 |
| --- | --- |
| `COURSE_ENABLED=true` | 启用课程生成入口；未提供配置时后端 Settings 默认关闭 |
| `COURSE_PROVIDER_TIMEOUT_SECONDS=120` | 单次课程模型请求的超时秒数 |
| `COURSE_JOB_DEADLINE_SECONDS=300` | 课程生成任务的执行期限秒数 |

实际模型请求还受任务剩余时间限制，读取已保存内容不触发模型调用。配置沿用当前 LLM 服务，不需要单独运行一个技能执行器。

## v2 目标与质量协作接口

模型草案只包含 `course_criterion_ref`。目标清单的描述与 mission.success_criteria 完全对应，课时保存讲解、示例、检查之间的局部 alignment。稳定 `course_criterion_id` 与 `criteria_revision` 由 A07 的发布事务负责，目标定义与学习结果分开；旧课的无模型懒映射标为 `legacy_unmapped`，不能推测题目关系或补写 verified。

生成器暴露一次外呼 `generate_once`，普通 fast 入口仅允许一次结构修复。启用 T02 guided 协作时，Planner、Teacher、Reviewer 使用同一任务的来源、租约、预算与截止时间；结构修复和质量返修共享一个槽。审核报告绑定 canonical draft_hash，只能评价其实际看到的候选稿，审核通过不是正式成绩。

已发布正文不能被审课直接覆盖。局部修订由 B06 的显式新 revision 与确认发布入口处理；原题目、作答和评分保留原版本关系。T01 本身不创建目标表、学习事实或修订接口。

实现依据：[课程路由](../../../../backend/app/api/v1/routes/courses.py)、[生成器](../../../../backend/app/teaching/generator.py)、[课程练习](../../../../backend/app/services/course_quiz_service.py)、[课程统计](../../../../backend/app/services/course_progress.py)、[环境模板](../../../../deploy/env.example)。

## 未接入工具时的执行方式

- 材料可用时，输出课程、单课、今日学习建议或反馈的 `draft`；清楚标明尚未保存到循课项目。
- 用顺序编号或“待绑定”表达课程关联；真实 `space_id`、`unit_id`、`concept_id`、`attempt_id` 等只采用可信输入或工具返回值。
- 不写 SQL、不直接改数据库、不自行构造服务调用成功的回执，也不把聊天输出描述成新增了空间、题目或复习任务。
- 知识库资料仅在应用内可见而当前没有访问工具时，保持 `strict_docs` 并说明缺少的内容；结构化输出使用 `needs_sources` 且 `payload=null`，不伪装完成 RAG。
- 原版 teach 的 `MISSION`、`RESOURCES`、本地学习记录与 HTML 看板在这里分别对应目标、来源、续学摘要和可选展示；它们不再是使用技能前必须创建的文件。
- 用户另行要求导出时才生成相应文件；导出文件仍不等于已保存到应用或已在网站展示。
