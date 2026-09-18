import type {
  CourseLessonView,
  CourseProgressView,
  CourseTodayView,
  CourseView,
} from '../src/types/course'

// Pure, deterministic data shared by E2E mocks and visual previews. No browser setup here.
export const courseFixture: CourseView = {
  course_id: 'course-design-python',
  title: 'Python 函数与数据处理：从重复操作到可复用的程序',
  source_policy: 'topic',
  source_status: 'active',
  status: 'partial',
  outline_editable: false,
  revision: 1,
  criteria_revision: 1,
  teaching_mode: 'fast',
  created_at: '2026-09-14T08:00:00Z',
  updated_at: '2026-09-16T08:00:00Z',
  resume_lesson_id: 'lesson-functions',
  mission: {
    goal: '理解函数的输入与输出，把重复的数据处理步骤整理为可复用、可检查的程序。',
    daily_minutes: 20,
    prior_knowledge: ['认识变量与列表'],
    success_criteria: ['能定义并调用一个函数', '能解释参数与返回值的作用'],
  },
  lessons: [
    {
      lesson_id: 'lesson-values',
      title: '变量与数据',
      unit_ref: 'unit-1',
      position: 1,
      availability: 'ready',
      status: 'ready',
      revision: 1,
      content_version: 1,
      read_at: '2026-09-14T09:00:00Z',
      estimated_minutes: 10,
    },
    {
      lesson_id: 'lesson-lists',
      title: '列表与重复操作',
      unit_ref: 'unit-2',
      position: 2,
      availability: 'ready',
      status: 'ready',
      revision: 1,
      content_version: 1,
      read_at: '2026-09-15T09:00:00Z',
      estimated_minutes: 12,
    },
    {
      lesson_id: 'lesson-functions',
      title: '函数的参数与返回值',
      unit_ref: 'unit-3',
      position: 3,
      availability: 'ready',
      status: 'ready',
      revision: 1,
      content_version: 1,
      estimated_minutes: 15,
      objective: '区分函数的输入、处理过程与输出。',
    },
    {
      lesson_id: 'lesson-pipeline',
      title: '组合数据处理步骤',
      unit_ref: 'unit-4',
      position: 4,
      availability: 'ready',
      status: 'not_generated',
      revision: 1,
      content_version: 0,
      estimated_minutes: 15,
    },
    {
      lesson_id: 'lesson-gap',
      title: '扩展：外部数据接口',
      unit_ref: 'unit-5',
      position: 5,
      availability: 'material_gap',
      status: 'material_gap',
      revision: 1,
      content_version: 0,
    },
  ],
  warnings: [],
}

export const courseLessonFixture: CourseLessonView = {
  course_id: courseFixture.course_id,
  lesson_id: 'lesson-functions',
  title: '函数的参数与返回值',
  objective: '区分函数的输入、处理过程与输出，并用一个小程序验证自己的理解。',
  status: 'ready',
  revision: 1,
  content_version: 1,
  estimated_minutes: 15,
  read_at: null,
  blocks: [
    {
      type: 'explanation',
      synthetic: false,
      text: '函数把一段可以重复使用的操作组织在一起。调用函数时，参数把数据送入函数；执行完成后，返回值把结果交还给调用者。\n\n可以把它看作一份小配方：输入说明需要什么材料，函数体记录处理步骤，返回值则是最后得到的结果。明确这三个部分，才能在更换输入时判断程序是否仍然正确。',
    },
    {
      type: 'example',
      synthetic: true,
      text: '下面用一个计算平均值的函数观察数据如何流动。\n\n```python\ndef average(values):\n    total = sum(values)\n    return total / len(values)\n\nmeasurements_for_the_current_learning_experiment = [12, 18, 24, 30]\nresult = average(measurements_for_the_current_learning_experiment)\nprint(result)\n```\n\n列表是输入，求和与除法是处理过程，得到的平均值是输出。示例假设列表不为空。',
    },
    {
      type: 'reference',
      synthetic: false,
      text: '这是一门主题课程，当前讲解基于通用知识，没有已保存的资料原文引用。示例用于说明输入与输出，不代表处理所有异常情况的完整程序。',
    },
    {
      type: 'recap',
      synthetic: false,
      text: '参数描述函数需要的数据，返回值描述函数提供的结果。定义时写清输入与输出，调用时检查传入的数据是否满足前提。\n\n试着用一句话说明：为什么显示结果与返回结果不是同一件事？',
    },
  ],
  checks: [
    {
      check_ref: 'check-return',
      question_type: 'reflection',
      prompt: '如果要让另一个函数继续处理平均值，为什么应该使用 return？',
      options: [],
    },
  ],
  sources: [],
  quiz_links: [],
  warnings: [],
  next_step: '用不同的列表调用这个函数，观察返回值如何变化。',
}

export const courseProgressFixture: CourseProgressView = {
  course_id: courseFixture.course_id,
  total_lessons: 5,
  available_lessons: 4,
  generated_lessons: 3,
  read_lessons: 2,
  practiced_lessons: 0,
  initial_answered: 0,
  initial_correct: 0,
  initial_accuracy: null,
  next_action: {
    type: 'learn_lesson',
    lesson_id: courseLessonFixture.lesson_id,
    reason: '继续尚未读完的函数课时。',
  },
  pending_weak_points: [],
  weak_points: [],
  review_runs: [],
}

export const courseTodayFixture: CourseTodayView = {
  local_date: '2026-09-16',
  timezone: 'Asia/Shanghai',
  minutes_budget: 20,
  items: [
    {
      kind: 'learn_lesson',
      course_id: courseFixture.course_id,
      lesson_id: courseLessonFixture.lesson_id,
      title: courseLessonFixture.title,
      reason: '接上已经完成的列表学习，理解可复用的数据处理步骤。',
      estimated_minutes: 15,
    },
    {
      kind: 'practice_lesson',
      course_id: courseFixture.course_id,
      lesson_id: courseLessonFixture.lesson_id,
      title: '用一组练习检查函数的输入与输出',
      reason: '读完后再作答，把刚理解的概念用起来。',
      estimated_minutes: 5,
    },
  ],
  warnings: [],
}

export const unstartedCourseFixture: CourseView = {
  ...courseFixture,
  course_id: 'course-design-probability',
  title: '概率与日常判断',
  status: 'ready',
  resume_lesson_id: null,
  mission: { goal: '从生活中的不确定性出发，理解概率与条件概率。', daily_minutes: 10 },
  lessons: [
    {
      lesson_id: 'probability-first',
      title: '随机事件',
      unit_ref: 'unit-1',
      position: 1,
      availability: 'ready',
      status: 'not_generated',
      revision: 1,
      content_version: 0,
    },
  ],
}

export const revokedCourseFixture: CourseView = {
  ...courseFixture,
  course_id: 'course-design-revoked',
  title: '不得显示的私密资料标题',
  source_policy: 'strict_docs',
  source_status: 'revoked',
  status: 'source_revoked',
  mission: { goal: '不得显示的私密学习目标' },
}

export const courseListFixture = [courseFixture, unstartedCourseFixture, revokedCourseFixture]
