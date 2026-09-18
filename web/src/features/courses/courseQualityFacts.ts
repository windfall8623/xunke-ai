import type {
  CourseTaskView,
  CourseTeachingMode,
  TeachingQualitySummary,
} from '../../types/course'

/** 与 CourseTaskStatus 的阶段文案保持一致；这些值都映射到真实的公开阶段回调。 */
export const TEACHING_STAGE_LABELS = {
  planning: '课程设计',
  teaching: '讲解生成',
  reviewing: '教学检查',
  revising: '根据反馈修订',
} as const

export type TeachingRoleStage = keyof typeof TEACHING_STAGE_LABELS

const ROLE_STAGES = Object.keys(TEACHING_STAGE_LABELS) as TeachingRoleStage[]

export function isTeachingRoleStage(stage?: string | null): stage is TeachingRoleStage {
  return !!stage && (ROLE_STAGES as string[]).includes(stage)
}

export type TeachingQualityFact = {
  /** 可以对用户显示的结论。只有绑定当前产物的通过报告才是 reviewed。 */
  status: 'reviewed' | 'needs_revision' | 'unreviewed'
  /** 服务端声明为 reviewed，但报告没有绑定当前正式内容。 */
  unbound: boolean
  /** 本次生成是否请求过教学核对。 */
  reviewRequested: boolean
  reasonCode: string | null
  reason: string
  warnings: string[]
}

const REASON_TEXT: Record<string, string> = {
  not_requested: '本次生成未请求教学核对。',
  legacy_content: '这部分内容在教学核对上线前生成，没有核对记录。',
  content_changed: '内容在核对之后发生了变化，原核对结果不适用于当前版本。',
  review_pending: '教学核对尚未产生可用于本版内容的结论。',
  review_timeout: '教学核对超时结束，本次没有得到结论。',
  review_budget: '本次任务的调用额度用完，教学核对没有完成。',
  review_budget_or_deadline: '剩余额度或时间不足，本次没有执行教学核对。',
  review_provider_unavailable: '教学核对所需的模型服务暂不可用。',
  review_binding_mismatch: '核对结果与当前草稿不对应，未采纳该结论。',
  source_revoked: '课程资料已失效，相关核对内容已清除。',
  generation_stopped: '本次生成提前结束，教学核对没有完成。',
}

/**
 * 质量摘要的可展示事实。
 *
 * 硬约束：`reviewed` 必须同时具备通过状态与当前产物哈希。服务端只在报告绑定
 * 已发布产物时提供 `artifact_hash`，因此缺少该哈希的 `reviewed` 一律降级，
 * 不能对用户宣称内容已经过教学核对。`draft_hash` 只用于判断，不展示给用户。
 */
export function teachingQualityFact(
  summary: TeachingQualitySummary | null | undefined,
  mode: CourseTeachingMode,
  { reviewRequested = mode === 'guided' }: { reviewRequested?: boolean } = {},
): TeachingQualityFact {
  const bound = !!summary?.artifact_hash?.trim()
  const claimed = summary?.status === 'reviewed'
  const unbound = claimed && !bound
  const status: TeachingQualityFact['status'] = claimed
    ? bound
      ? 'reviewed'
      : 'unreviewed'
    : summary?.status === 'needs_revision'
      ? 'needs_revision'
      : 'unreviewed'
  const reasonCode = unbound ? 'content_changed' : summary?.reason_code || null
  const reason = unbound
    ? REASON_TEXT.content_changed
    : reasonCode && REASON_TEXT[reasonCode]
      ? REASON_TEXT[reasonCode]
      : status === 'reviewed'
        ? ''
        : reviewRequested
          ? '本版内容尚未取得有效的教学核对结论。'
          : REASON_TEXT.not_requested
  return {
    status,
    unbound,
    reviewRequested,
    reasonCode,
    reason,
    // 提示性发现只在核对确实通过时才有意义。
    warnings: status === 'reviewed' ? summary?.warnings || [] : [],
  }
}

export const QUALITY_STATUS_LABELS: Record<TeachingQualityFact['status'], string> = {
  reviewed: '本版内容已完成教学核对',
  needs_revision: '发现需要修改的内容，本次新稿尚未发布',
  unreviewed: '本版内容尚未完成教学核对',
}

export type AgentStepState = 'done' | 'active' | 'expected' | 'conditional' | 'unknown'

export type AgentStep = {
  stage: TeachingRoleStage
  label: string
  state: AgentStepState
}

export type AgentProgressFact = {
  /** 是否有可展示的真实角色协作。false 时不显示任何角色阶段。 */
  collaborating: boolean
  running: boolean
  reviewRequested: boolean
  /** 课时任务读取已保存的课程规划，不产生新的规划外呼。 */
  planReused: boolean
  currentStage: TeachingRoleStage | null
  steps: AgentStep[]
}

/**
 * 角色进度的可展示事实。
 *
 * 硬约束：只有任务真实进入过角色阶段（`planning`/`teaching`/`reviewing`/`revising`）
 * 才展示角色协作。阶段状态全部来自当前阶段，不推算百分比、不预测完成时间，
 * 也不把尚未发生的核对或返修标成已完成。
 */
export function agentProgressFact(
  task: Pick<CourseTaskView, 'kind' | 'stage' | 'status'> | null | undefined,
  mode: CourseTeachingMode,
  { reviewRequested = mode === 'guided' }: { reviewRequested?: boolean } = {},
): AgentProgressFact {
  const stage = task?.stage
  const currentStage = isTeachingRoleStage(stage) ? stage : null
  const running = task?.status === 'pending' || task?.status === 'running'
  const outline = task?.kind === 'course_outline'
  const empty: AgentProgressFact = {
    collaborating: false,
    running: !!running,
    reviewRequested,
    planReused: false,
    currentStage: null,
    steps: [],
  }
  // 没有观察到角色阶段时不虚构协作过程：fast 直连生成也走这条分支。
  if (!task || !currentStage) return empty
  const generate: TeachingRoleStage = outline ? 'planning' : 'teaching'
  const order: TeachingRoleStage[] = [generate, 'reviewing', 'revising']
  const index = order.indexOf(currentStage)
  const state = (candidate: TeachingRoleStage): AgentStepState => {
    if (candidate === currentStage) return running ? 'active' : 'unknown'
    const position = order.indexOf(candidate)
    // 任务已结束时，未观察到的阶段结果未知，不追认为已完成。
    if (!running) return position < index ? 'done' : 'unknown'
    if (position < index) return 'done'
    return candidate === 'revising' ? 'conditional' : 'expected'
  }
  const steps: AgentStep[] = [generate, ...(reviewRequested || index > 0 ? (['reviewing'] as const) : [])]
    .map((candidate) => ({ stage: candidate, label: TEACHING_STAGE_LABELS[candidate], state: state(candidate) }))
  // 返修只在实际发生或仍可能发生时列出，不作为常规步骤展示。
  if (currentStage === 'revising' || (running && index >= 0 && reviewRequested))
    steps.push({ stage: 'revising', label: TEACHING_STAGE_LABELS.revising, state: state('revising') })
  return {
    collaborating: true,
    running: !!running,
    reviewRequested: reviewRequested || index > 0,
    planReused: !outline,
    currentStage,
    steps,
  }
}

export const AGENT_STEP_STATE_LABELS: Record<AgentStepState, string> = {
  done: '已完成',
  active: '正在进行',
  expected: '待进行',
  conditional: '如有需要才进行',
  unknown: '结果未知',
}
