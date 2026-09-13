import type {
  CourseApplicationAttemptView,
  CourseAssessmentView,
  CourseCriterion,
  CourseCriterionOutcome,
  CourseOutcomeStatus,
  CourseOutcomeSummary,
} from '../../types/course'

export const OUTCOME_STATUS_LABELS: Record<CourseOutcomeStatus, string> = {
  verified: '已验证',
  needs_practice: '需补学',
  unverified: '待验证',
  stale: '证据已过期',
}

export const EVIDENCE_TYPE_LABELS: Record<CourseCriterion['evidence_type'], string> = {
  recognition: '识别',
  recall: '回忆',
  application: '应用',
  explanation: '表达',
  creation: '创建',
}

const ORIGIN_LABELS: Record<string, string> = {
  quiz: '客观检查',
  practice: '练习',
  course_application: '文本应用任务',
  self_check: '课内自检',
}

export function evidenceOriginLabel(kind: string) {
  return ORIGIN_LABELS[kind] || '学习记录'
}

/**
 * 只有服务端投影明确给出 `verified` 才算已验证。
 *
 * 硬约束：暂定评分、未知帮助情况、仅保存回答与自评都由服务端保持在
 * `unverified`；前端不再叠加任何“看起来通过了”的推断。
 */
export function isVerifiedOutcome(outcome: Pick<CourseCriterionOutcome, 'status'>) {
  return outcome.status === 'verified'
}

export type OutcomeTally = {
  total: number
  verified: number
  needsPractice: number
  unverified: number
  stale: number
}

export function outcomeTally(criteria: CourseCriterionOutcome[]): OutcomeTally {
  return {
    total: criteria.length,
    verified: criteria.filter((item) => item.status === 'verified').length,
    needsPractice: criteria.filter((item) => item.status === 'needs_practice').length,
    unverified: criteria.filter((item) => item.status === 'unverified').length,
    stale: criteria.filter((item) => item.status === 'stale').length,
  }
}

export type AssessmentGoal = {
  courseCriterionId: string
  title: string
  status: CourseOutcomeStatus
  reason: string
  evidenceCount: number
  covered: boolean
  definition?: CourseCriterion
}

/**
 * 把一次结业检查的覆盖范围与全课目标结果对齐。
 *
 * 一次检查只覆盖它实际映射的题目；未覆盖的目标必须保持可见，不能因为
 * 本次流程结束就当作整门课程已经检验。
 */
export function assessmentGoals(
  assessment: CourseAssessmentView | null | undefined,
  outcomes: CourseOutcomeSummary | null | undefined,
  definitions: CourseCriterion[] = [],
): AssessmentGoal[] {
  const covered = new Set(assessment?.covered_course_criterion_ids || [])
  const byId = new Map(definitions.map((item) => [item.course_criterion_id, item]))
  return (outcomes?.criteria || []).map((outcome) => ({
    courseCriterionId: outcome.course_criterion_id,
    title: outcome.title,
    status: outcome.status,
    reason: outcome.reason,
    evidenceCount: (outcome.evidence_refs || []).length,
    covered: covered.has(outcome.course_criterion_id),
    definition: byId.get(outcome.course_criterion_id),
  }))
}

/** 本次检查范围之外或未映射到题目的目标。 */
export function uncoveredGoals(goals: AssessmentGoal[]) {
  return goals.filter((goal) => !goal.covered)
}

export type AssessmentFlowState =
  | 'none'
  | 'generating'
  | 'ready'
  | 'in_progress'
  | 'ready_to_complete'
  | 'completed'
  | 'failed'
  | 'cancelled'

/**
 * 结业检查流程状态。
 *
 * `completed` 只表示本次检查流程已封存，与任何目标是否 `verified` 无关。
 */
export function assessmentFlowState(
  assessment: CourseAssessmentView | null | undefined,
): AssessmentFlowState {
  if (!assessment) return 'none'
  if (assessment.status === 'completed') return 'completed'
  if (assessment.status === 'failed') return 'failed'
  if (assessment.status === 'cancelled') return 'cancelled'
  if (assessment.status === 'generating') return 'generating'
  // 客观题已结算即可封存本次检查；封存与目标是否验证是两件事。
  if (assessment.quiz_settled) return 'ready_to_complete'
  return assessment.status === 'in_progress' ? 'in_progress' : 'ready'
}

export type ApplicationFeedbackState =
  | 'not_submitted'
  | 'queue_unavailable'
  | 'preparing'
  | 'syncing'
  | 'ready'
  | 'needs_review'
  | 'failed'
  | 'cancelled'

/**
 * 一次应用回答的反馈状态。
 *
 * 回答一旦保存就必须保持可见：排队失败、模型失败与取消都只影响反馈，
 * 不影响已保存的回答，也不能显示成尚未作答。
 */
export function applicationFeedbackState(
  attempt: CourseApplicationAttemptView | null | undefined,
): ApplicationFeedbackState {
  if (!attempt) return 'not_submitted'
  const task = attempt.feedback_task
  const feedback = attempt.feedback
  if (feedback) {
    if (feedback.status === 'graded') return 'ready'
    if (feedback.status === 'needs_review') return 'needs_review'
    return feedback.status === 'cancelled' ? 'cancelled' : 'failed'
  }
  if (!task) return attempt.feedback_task_id ? 'syncing' : 'queue_unavailable'
  if (task.status === 'pending' || task.status === 'running') return 'preparing'
  if (task.status === 'completed') return 'syncing'
  return task.status === 'cancelled' ? 'cancelled' : 'failed'
}

/**
 * 模型反馈是否只是暂定结论。
 *
 * `provisional` 与 `needs_review` 都不是正式评分；正式验证只能来自
 * `get_course_outcomes()` 的目标投影。
 */
export function isProvisionalFeedback(
  feedback: CourseApplicationAttemptView['feedback'] | null | undefined,
) {
  return !!feedback && (feedback.confirmation !== 'confirmed' || feedback.status !== 'graded')
}

export const CRITERION_CREDIT_LABELS: Record<string, string> = {
  full: '符合要求',
  half: '部分符合',
  none: '未达到',
  uncertain: '无法判断',
}

export function criterionCreditLabel(credit: unknown) {
  return typeof credit === 'string' ? CRITERION_CREDIT_LABELS[credit] || '待核对' : '待核对'
}

export const HELP_USAGE_LABELS = {
  none: '没有使用提示或帮助',
  hints: '使用过提示或帮助',
  unknown: '不确定',
} as const
