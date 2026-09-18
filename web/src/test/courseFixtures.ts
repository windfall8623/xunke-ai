import type { Quiz } from '../types/api'
import type {
  CourseApplicationAttemptView, CourseAssessmentView, CourseCriterion, CourseLessonView,
  CourseOutcomeSummary, CourseProgressView, CourseQuizLinkView, CourseSelfCheckView,
  CourseTodayView, CourseTutorTurnView, CourseView,
} from '../types/course'

/** Synthetic, saved business records. No provider calls or generated teaching claims. */
export const courseLessonFixture: CourseLessonView = {
  course_id: 'course-1', lesson_id: 'lesson-1', content_version: 1, revision: 1,
  title: '函数里的变量与作用域', status: 'ready', estimated_minutes: 20,
  objective: '能够解释函数中局部变量的可见范围。', read_at: null,
  blocks: [
    { type: 'explanation', text: '局部变量在函数内使用。函数外需要通过返回值获得结果。',
      source_refs: ['source-1'], synthetic: false },
    { type: 'example', text: '```python\ndef describe_scope():\n    local_message = "' + 'scope_example_'.repeat(18) + '"\n    return local_message\n```',
      synthetic: true, source_refs: [] },
    { type: 'recap', text: '先确认变量在哪里定义，再判断它能在哪些位置使用。',
      synthetic: false, source_refs: [] },
  ],
  checks: [
    { check_ref: 'check-1', question_type: 'reflection', prompt: '用自己的话解释局部变量的可见范围。', options: [] },
    { check_ref: 'check-2', question_type: 'single', prompt: '哪种方式能把函数的结果交给调用方？',
      options: [{ key: 'A', text: '使用返回值' }, { key: 'B', text: '读取任意局部变量' }] },
    { check_ref: 'check-3', question_type: 'multiple', prompt: '判断变量作用域时，需要检查哪些信息？',
      options: [{ key: 'A', text: '变量定义的位置' }, { key: 'B', text: '变量使用的位置' }] },
  ],
  next_step: '保存自己的解释，再用本课三题检查理解。', quiz_links: [], warnings: [],
  sources: [{ source_ref: 'source-1', title: '示例课程资料 · 函数作用域', kind: 'provided_material',
    locator: '第 2 节', document_version_id: 'version-1' }],
}

export const courseFixture: CourseView = {
  course_id: 'course-1', revision: 1, title: 'Python 函数入门', status: 'ready',
  source_policy: 'topic', source_status: 'active', outline_editable: false,
  teaching_mode: 'fast', criteria_revision: 1,
  created_at: '2026-09-13T01:00:00Z', updated_at: '2026-09-13T01:00:00Z',
  resume_lesson_id: 'lesson-1',
  mission: { goal: '读懂并解释函数的输入、作用域与返回值。', daily_minutes: 20,
    prior_knowledge: [], success_criteria: ['能解释变量作用域'] },
  lessons: [
    { lesson_id: 'lesson-1', unit_ref: 'unit-1', position: 1, title: courseLessonFixture.title,
      availability: 'ready', status: 'ready', content_version: 1, revision: 1, read_at: null },
    { lesson_id: 'lesson-2', unit_ref: 'unit-2', position: 2, title: '函数参数',
      availability: 'ready', status: 'ready', content_version: 1, revision: 1, read_at: null },
  ],
  sources: [], warnings: [],
}

export const courseCheckFixture: CourseSelfCheckView = {
  attempt_id: 'attempt-1', course_id: 'course-1', lesson_id: 'lesson-1', content_version: 1,
  check_ref: 'check-1', answer: '局部变量只在定义它的函数里可见。', saved_at: '2026-09-13T01:10:00Z',
}

export const courseTutorFixture: CourseTutorTurnView = {
  turn_id: 'turn-1', course_id: 'course-1', lesson_id: 'lesson-1', content_version: 1,
  mode: 'check', check_attempt_id: 'attempt-1', block_index: null, question: '',
  created_at: '2026-09-13T01:11:00Z', answer: null, sources: [], warnings: [],
  task: { task_id: 'tutor-task-1', course_id: 'course-1', lesson_id: 'lesson-1',
    kind: 'course_tutor', status: 'completed', stage: 'completed', business_settled: true },
}

export const courseQuizLinkFixture: CourseQuizLinkView = {
  link_id: 'link-1', lesson_id: 'lesson-1', content_version: 1, kind: 'initial',
  created_at: '2026-09-13T01:12:00Z',
  task: { task_id: 'quiz-task-1', status: 'completed', stage: 'completed',
    business_settled: true, quiz_id: 'course-quiz-1' },
}

export const courseQuizFixture: Quiz = {
  quiz_id: 'course-quiz-1', title: '变量作用域 · 本课三题', summary: '回看变量的定义与使用。',
  created_at: '2026-09-13T01:12:00Z', revision: 3, status: 'settled',
  source_policy: 'topic', source_status: 'verified', images_status: 'not_requested', report_status: 'not_started',
  course_context: { course_id: 'course-1', lesson_id: 'lesson-1', link_id: 'link-1', content_version: 1, kind: 'initial' },
  questions: [1, 2, 3].map((number) => ({ id: `cq-${number}`, type: 'single' as const,
    stem: `作用域检查 ${number}：函数如何返回结果？`,
    options: [{ key: 'A', text: '使用返回值' }, { key: 'B', text: '直接读取局部变量' }],
    knowledge_point: '局部变量作用域', difficulty: 'easy', image_status: 'not_requested', citation_refs: [] })),
  answer_records: [1, 2, 3].map((number) => ({ question_id: `cq-${number}`,
    selected_answers: [number === 3 ? 'B' : 'A'], correct_answers: ['A'], is_correct: number !== 3,
    duration_ms: 1200, explanation: '函数通过返回值向调用方提供结果。', citation_refs: [] })),
}

export const courseProgressFixture: CourseProgressView = {
  course_id: 'course-1', total_lessons: 2, available_lessons: 2, generated_lessons: 2,
  read_lessons: 1, practiced_lessons: 2, initial_answered: 6, initial_correct: 5, initial_accuracy: 5 / 6,
  pending_weak_points: [{ lesson_id: 'lesson-1', link_id: 'link-1', quiz_id: 'course-quiz-1',
    question_id: 'cq-3', knowledge_point: '局部变量作用域' }],
  weak_points: [], review_runs: [],
  next_action: { type: 'learn_lesson', lesson_id: 'lesson-2', reason: '接着学习函数参数。' },
}

/** A07：两个已发布的课程目标，一个识别类、一个创建类。 */
export const courseCriteriaFixture: CourseCriterion[] = [
  { course_criterion_id: 'criterion-scope', course_criterion_ref: 'c_scope', criteria_revision: 1,
    description: '能解释局部变量的可见范围', evidence_type: 'recognition',
    expectation: '能指出变量定义位置并说明可用范围。', lesson_ids: ['lesson-1'], origin: 'generated_v2' },
  { course_criterion_id: 'criterion-build', course_criterion_ref: 'c_build', criteria_revision: 1,
    description: '能写出一个带返回值的函数', evidence_type: 'creation',
    expectation: '能独立写出函数并说明返回值用途。', lesson_ids: ['lesson-2'], origin: 'generated_v2' },
]

export const courseOutcomesFixture: CourseOutcomeSummary = {
  course_id: 'course-1', criteria_revision: 1,
  criteria: [
    { course_criterion_id: 'criterion-scope', criteria_revision: 1, title: courseCriteriaFixture[0].description,
      status: 'unverified', reason: '检查成绩已保留，但帮助使用情况未知或存在提示，尚不能确认独立完成。',
      evidence_refs: [{ origin_kind: 'quiz', origin_id: 'assessment-quiz-1', occurred_at: '2026-09-13T02:00:00Z' }] },
    { course_criterion_id: 'criterion-build', criteria_revision: 1, title: courseCriteriaFixture[1].description,
      status: 'unverified', reason: '尚无已结算且明确对应本目标的学习证据。', evidence_refs: [] },
  ],
}

/** 一次已结算的客观检查，只映射到识别类目标；创建类目标保持未覆盖。 */
export const courseAssessmentFixture: CourseAssessmentView = {
  course_assessment_id: 'assessment-1', course_id: 'course-1', criteria_revision: 1, revision: 3,
  status: 'in_progress', task_id: 'assessment-task-1',
  task: { task_id: 'assessment-task-1', status: 'completed', stage: 'completed', business_settled: true },
  quiz_id: 'assessment-quiz-1', quiz_status: 'settled', quiz_settled: true,
  application_task_ids: [], applications: [],
  covered_course_criterion_ids: ['criterion-scope'],
  uncovered_course_criterion_ids: ['criterion-build'],
}

export const courseApplicationFixture: CourseAssessmentView['applications'] = [
  { application_task_id: 'application-1', revision: 1, response_format: 'text',
    prompt: '写出一个统计已支付订单总额的函数，并解释返回值的用途。',
    public_expectations: ['说明函数的输入', '说明返回值的用途'], source_policy: 'topic',
    source_refs: [], support_quotes: [], course_criterion_ids: ['criterion-build'], latest_attempt_id: null },
]

/** 回答已保存但反馈排队失败：answer 必须保留，且不显示为已验证。 */
export const courseApplicationAttemptFixture: CourseApplicationAttemptView = {
  attempt_id: 'application-attempt-1', application_task_id: 'application-1',
  course_assessment_id: 'assessment-1', course_id: 'course-1', revision: 1,
  question_version: 'question-v1', answer: '先按客户分组，再对已支付订单求和，函数返回该汇总结果。',
  help_usage: 'unknown', help_usage_source: 'unknown', saved_at: '2026-09-13T02:10:00Z',
  feedback_task_id: null, feedback_task: null, feedback: null,
}

export const courseTodayFixture: CourseTodayView = {
  timezone: 'Asia/Shanghai', local_date: '2026-09-13', minutes_budget: 20, warnings: [],
  items: [
    { kind: 'learn_lesson', course_id: 'course-1', lesson_id: 'lesson-1',
      title: courseLessonFixture.title, reason: '从上次停下的地方继续。', estimated_minutes: 10 },
    { kind: 'practice_lesson', course_id: 'course-2', lesson_id: 'lesson-other',
      title: '另一门课程的练习', reason: '回顾已经读过的内容。', estimated_minutes: 10 },
  ],
}
