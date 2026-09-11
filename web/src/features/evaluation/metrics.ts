export type Metric = {
  value: number | null
  unit?: string
  status?: string
  reason?: string
  sample_count?: number
  confidence_interval?: [number, number] | null
  failure_count?: number
  version?: string
  denominator?: number
  applicable_count?: number
  error_count?: number
  unknown_count?: number
}
const unavailable = new Set(['unknown', 'na', 'n/a', 'incomplete', 'pending', 'error', 'failed'])
function hasValue(metric: Metric | undefined): metric is Metric & { value: number } {
  return (
    metric != null &&
    metric.value != null &&
    Number.isFinite(metric.value) &&
    !(metric.unknown_count && metric.unknown_count > 0) &&
    !unavailable.has(metric.status?.toLowerCase() || '')
  )
}
export function formatGradeScore(score: unknown, status: unknown): string {
  if (
    status !== 'graded' ||
    typeof score !== 'string' ||
    !/^-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(score)
  )
    return '未知'
  const value = Number(score)
  if (
    !Number.isFinite(value) ||
    value < 0 ||
    value > 1 ||
    (value === 0 && /[1-9]/.test(score.split(/[eE]/)[0]))
  )
    return '未知'
  return value.toLocaleString('zh-CN', { style: 'percent', maximumSignificantDigits: 6 })
}

const basicMetrics: Record<string, Set<string>> = {
  practice_generation: new Set([
    'practice_outcome_match',
    'practice_failure_behavior_match',
    'question_schema_pass',
    'valid_question_yield',
    'full_set_pass',
    'answer_correctness',
    'source_support',
    'context_evidence_group_recall',
    'citation_id_validity',
    'citation_support',
    'total_cost_cny',
    'end_to_end_latency_ms',
    'service_failure',
  ]),
  answer_grading: new Set([
    'grading_status_match',
    'grading_abs_error',
    'grading_false_accept_rate',
    'grading_review_rate',
    'confirmation_policy_pass',
    'learning_evidence_eligible',
    'citation_id_validity',
    'total_cost_cny',
    'grading_latency_ms',
    'service_failure',
  ]),
}
export function isBasicMetric(caseType: string, name: string): boolean {
  return !basicMetrics[caseType] || basicMetrics[caseType].has(name)
}
export function formatMetric(metric: Metric | undefined): string {
  if (!hasValue(metric)) return '—'
  if (metric.unit === 'ratio' || metric.unit === 'proportion')
    return `${(metric.value * 100).toFixed(1)}%`
  if (metric.unit === 'percent' || metric.unit === '%') return `${metric.value.toFixed(1)}%`
  if (metric.unit === 'CNY' || metric.unit === 'CNY/question')
    return `${metric.value.toLocaleString('zh-CN', { maximumSignificantDigits: 6, useGrouping: false })} ${metric.unit}`
  return `${Number(metric.value.toFixed(3))}${metric.unit && metric.unit !== 'count' ? ` ${metric.unit}` : ''}`
}
export function formatDifference(
  baseline: Metric | undefined,
  candidate: Metric | undefined,
): string {
  if (!hasValue(baseline) || !hasValue(candidate) || baseline.unit !== candidate.unit) return '—'
  const difference = candidate.value - baseline.value
  const prefix = difference > 0 ? '+' : ''
  if (candidate.unit === 'ratio' || candidate.unit === 'proportion')
    return `${prefix}${(difference * 100).toFixed(1)} 个百分点`
  if (candidate.unit === 'percent' || candidate.unit === '%')
    return `${prefix}${difference.toFixed(1)} 个百分点`
  return `${prefix}${Number(difference.toFixed(3))}${candidate.unit ? ` ${candidate.unit}` : ''}`
}
