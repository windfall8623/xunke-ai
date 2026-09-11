import type { DatasetSample, EvaluationCaseType, SourceExcerpt } from '../../types/evaluation'

export const caseLabels: Record<EvaluationCaseType, string> = {
  retrieval: '检索',
  quiz: '出题',
  policy: '策略',
  qa: '问答',
  practice_generation: '练习生成',
  answer_grading: '答案判分',
}
export const practiceTypeLabels = { cloze: '填空', numeric: '数值', short_answer: '简答' }

export function samplePrompt(sample: DatasetSample): string {
  if (sample.case_type === 'practice_generation')
    return sample.spec?.objectives.join('；') || '练习生成样本'
  if (sample.case_type === 'answer_grading')
    return typeof sample.question === 'object' && sample.question
      ? sample.question.stem
      : '答案判分样本'
  return (
    (typeof sample.question === 'string' ? sample.question : null) ||
    sample.query ||
    sample.user_input ||
    '策略验证样本'
  )
}

function record(value: unknown): Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function validateLearningFields(value: Record<string, unknown>) {
  const error = (message: string) => new Error(`${value.sample_id}：${message}`)
  if (value.case_type === 'practice_generation') {
    const spec = record(value.spec)
    if (
      !Array.isArray(spec.question_types) ||
      !spec.question_types.length ||
      !spec.question_types.every(
        (kind) => typeof kind === 'string' && Object.hasOwn(practiceTypeLabels, kind),
      )
    )
      throw error('spec.question_types 需要包含填空、数值或简答题型。')
    if (
      !Array.isArray(spec.objectives) ||
      !spec.objectives.length ||
      !spec.objectives.every((objective) => typeof objective === 'string' && objective.trim())
    )
      throw error('spec.objectives 需要填写学习目标。')
    if (
      !Number.isInteger(spec.question_count) ||
      Number(spec.question_count) < 3 ||
      Number(spec.question_count) > 10
    )
      throw error('spec.question_count 必须为 3–10。')
    if (!['generate', 'refuse', 'failed'].includes(String(value.expected_outcome)))
      throw error('expected_outcome 需要为 generate、refuse 或 failed。')
    if (
      value.expected_outcome === 'failed' &&
      (typeof value.expected_error_code !== 'string' || !value.expected_error_code.trim())
    )
      throw error('预期执行失败需要 expected_error_code。')
    if (value.expected_outcome === 'generate' && value.expected_error_code != null)
      throw error('预期生成成功时不能同时声明 expected_error_code。')
  }
  if (value.case_type === 'answer_grading') {
    const question = record(value.question)
    const answer = record(value.answer)
    if (
      typeof value.question_type !== 'string' ||
      !Object.hasOwn(practiceTypeLabels, value.question_type) ||
      question.type !== value.question_type ||
      answer.type !== value.question_type
    )
      throw error('question、answer 和 question_type 的题型必须一致。')
    for (const field of ['question_version', 'rubric_hash', 'response_hash'])
      if (typeof value[field] !== 'string' || !/^[a-f0-9]{64}$/.test(value[field] as string))
        throw error(`${field} 需要保留原始的 64 位 hash。`)
    if (
      !['graded', 'needs_review', 'failed', 'cancelled'].includes(
        String(value.expected_grade_status),
      )
    )
      throw error('请填写有效的 expected_grade_status。')
    const reference = record(value.reference_grade)
    if (
      reference.score != null &&
      (typeof reference.score !== 'string' ||
        !/^-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(reference.score) ||
        !Number.isFinite(Number(reference.score)) ||
        Number(reference.score) < 0 ||
        Number(reference.score) > 1)
    )
      throw error('reference_grade.score 需要为 0–1 的十进制字符串或 null；未知分数请保留 null。')
    if (reference.status && reference.status !== 'graded' && reference.score != null)
      throw error('未完成参考判分时，reference_grade.score 必须保留 null。')
  }
}

export function parseSamples(text: string): DatasetSample[] {
  const clean = text.replace(/^\uFEFF/, '').trim()
  if (!clean) throw new Error('至少导入一条包含 sample_id 的样本。')
  let values: unknown
  try {
    values = clean.startsWith('[')
      ? JSON.parse(clean)
      : clean
          .split(/\r?\n/)
          .filter((line) => line.trim())
          .map((line) => JSON.parse(line))
  } catch {
    throw new Error('样本 JSON / JSONL 格式无效，请检查后再导入。')
  }
  if (!Array.isArray(values) || !values.length)
    throw new Error('样本必须为包含 sample_id 的数组或 JSONL。')
  const ids = new Set<string>()
  for (const value of values) {
    if (
      !value ||
      typeof value !== 'object' ||
      typeof value.sample_id !== 'string' ||
      !value.sample_id.trim() ||
      ids.has(value.sample_id)
    )
      throw new Error('每条样本必须有唯一且非空的 sample_id。')
    ids.add(value.sample_id)
  }
  for (const value of values) {
    if (typeof value.case_type !== 'string' || !Object.hasOwn(caseLabels, value.case_type))
      throw new Error(
        `${value.sample_id}：case_type 需要为检索、出题、策略、问答、练习生成或答案判分。`,
      )
    validateLearningFields(value)
  }
  return values as DatasetSample[]
}
export function buildGoldSpan(source: SourceExcerpt): Record<string, unknown> {
  const { start_char: start, end_char: end, quote_hash: quoteHash } = source.locator
  if (
    ![
      source.doc_id,
      source.version_id,
      source.parse_artifact_id,
      source.canonical_text_hash,
      source.block_id,
      quoteHash,
    ].every((value) => typeof value === 'string' && value.length > 0) ||
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    Number(start) < 0 ||
    Number(end) <= Number(start)
  )
    throw new Error('片段缺少完整定位或原文 hash，不能自动建立证据标注。')
  return {
    doc_id: source.doc_id,
    source_version_id: source.version_id,
    parse_artifact_id: source.parse_artifact_id,
    canonical_text_hash: source.canonical_text_hash,
    block_id: source.block_id,
    start_char: start,
    end_char: end,
    quote_hash: quoteHash,
  }
}
