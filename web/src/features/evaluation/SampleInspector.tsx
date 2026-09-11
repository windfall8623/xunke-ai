import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Save } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ErrorNotice, StatusBadge } from '../../components/ui'
import { evaluationApi } from '../../services/evaluation'
import type { EvalResult, HumanReview, QuestionReview } from '../../types/evaluation'
import { formatGradeScore, formatMetric, isBasicMetric, type Metric } from './metrics'
import { practiceTypeLabels, samplePrompt } from './dataset'
import { JsonView, failureCategory, failureLabels, objectValue, textValue } from './WorkbenchNav'

export const metricLabel: Record<string, string> = {
  faithfulness: '事实支持度（自动评分）',
  answer_relevancy: '回答相关性（自动评分）',
  context_evidence_group_recall: '最终上下文证据组覆盖率',
  context_all_evidence: '完整证据覆盖',
  context_redundancy: '上下文冗余率',
  evidence_retention: '证据保留率',
  context_tokens: '上下文 Token',
  candidate_count: '候选数量',
  valid_question_yield: '有效题产出率',
  complete_quiz_pass_rate: '完整套题通过率',
  cost_per_valid_question: '每道有效题成本',
  qa_answer_status_match: '问答状态符合率',
  qa_answer_structure_validity: '回答结构有效率',
  qa_citation_validity: '引用身份有效率',
  qa_fact_citation_coverage: '事实块引用覆盖率',
  qa_evidence_group_recall: '问答证据组覆盖率',
  qa_all_evidence_hit: '问答证据完整命中率',
  qa_failure_behavior_match: '故障保护符合率',
  qa_correctness: '问答正确性',
  qa_faithfulness: '问答忠实度',
  service_failure: '执行失败',
  practice_outcome_match: '生成结果符合预期',
  practice_failure_behavior_match: '生成故障保护',
  practice_identity_match: '题目版本与规则一致性',
  question_schema_pass: '题目结构有效率',
  question_count_pass: '题量符合率',
  full_set_pass: '完整套题通过率',
  answer_correctness: '生成答案正确性',
  source_support: '答案有原文支持',
  solvability: '题目可解性',
  citation_id_validity: '引用身份有效率',
  citation_authorization: '引用授权有效率',
  citation_hash_match: '引用原文一致率',
  citation_locator_match: '引用位置有效率',
  citation_support: '引用支持度',
  citation_completeness: '引用完整性',
  grading_status_match: '判分状态符合预期',
  grading_abs_error: '判分绝对误差',
  grading_false_accept_rate: '误判通过率',
  grading_review_rate: '待复核率',
  grading_failure_rate: '判分失败率',
  grading_failure_behavior_match: '判分故障保护',
  grading_identity_match: '题目与答案版本一致性',
  confirmation_policy_pass: '确认策略符合率',
  learning_evidence_eligible: '独立学习证据资格',
  provider_call_count: '模型与工具调用次数',
  unknown_call_count: '费用未知的调用次数',
  total_cost_cny: '总费用',
  reserved_cost_cny: '调用预留费用',
  unknown_reserved_cost_cny: '待结算的未知费用预留',
  generation_cost_cny: '生成费用',
  judge_cost_cny: '外部评审费用',
  cost_per_valid_question_cny: '每道有效题成本',
  grading_latency_ms: '判分耗时',
  queue_latency_ms: '排队耗时',
  execution_latency_ms: '执行耗时',
  end_to_end_latency_ms: '总耗时',
}
const answerStatusLabels: Record<string, string> = {
  answered: '已回答',
  partial: '部分回答',
  needs_clarification: '需要澄清',
  insufficient_evidence: '资料不足',
  conflicting_sources: '资料存在冲突',
}
const rubricLabels: Record<string, string> = {
  answer_correctness: '答案正确',
  source_support: '答案有原文支持',
  solvability: '题目可解',
  explanation_correctness: '解析正确',
  scope_compliance: '符合选定范围',
  citation_support: '引用支持结论',
  citation_completeness: '引用覆盖完整',
  stem_premise_support: '题干前提有依据',
  distractor_quality: '干扰项质量合格',
}
const gradeStatusLabels: Record<string, string> = {
  graded: '已判分',
  needs_review: '待复核',
  failed: '判分失败',
  cancelled: '已取消',
}
const gradeSourceLabels: Record<string, string> = {
  deterministic: '规则判分',
  model: '模型判分',
  human: '人工判分',
}

function MetricCard({ name, metric }: { name: string; metric: Metric }) {
  return (
    <div className="metric-card">
      <span>{metricLabel[name] || name}</span>
      <strong data-testid={`${name}-value`}>{formatMetric(metric)}</strong>
      <div>
        <StatusBadge status={metric.status || 'ok'}>
          {metric.reason === 'not_evaluated'
            ? '未评估'
            : metric.status === 'na'
              ? '不适用 · NA'
              : metric.status === 'error' ||
                  metric.status === 'unknown' ||
                  (metric.unknown_count || 0) > 0
                ? '评分待裁决'
                : metric.status === 'provisional'
                  ? '暂定结果'
                  : '已有观测'}
        </StatusBadge>
        {metric.reason && <small>{metric.reason}</small>}
      </div>
      {(metric.applicable_count ?? metric.sample_count) != null && (
        <small>适用样本 n = {metric.applicable_count ?? metric.sample_count}</small>
      )}
      {metric.denominator != null && <small>指标分母 = {metric.denominator}</small>}
      {(metric.error_count || metric.unknown_count || 0) > 0 && (
        <small>未裁决 / 错误 = {metric.error_count || metric.unknown_count}</small>
      )}
    </div>
  )
}
export function SampleInspector({
  runId,
  result,
  onSaved,
}: {
  runId: string
  result: EvalResult
  onSaved: () => void
}) {
  const artifact = result.artifact || {}
  const isQa = result.case_type === 'qa'
  const isPractice = result.case_type === 'practice_generation'
  const isGrading = result.case_type === 'answer_grading'
  const practice = objectValue(artifact.practice)
  const grade = objectValue(artifact.grade)
  const assessment = objectValue(grade.assessment)
  const questionPayload = isPractice ? practice.questions : artifact.questions
  const questions = Array.isArray(questionPayload)
    ? questionPayload.map(objectValue).filter((question) => question.id || question.question_id)
    : []
  const reviewLabels = isPractice
    ? Object.fromEntries(
        Object.entries(rubricLabels).filter(
          ([name]) => !['stem_premise_support', 'distractor_quality'].includes(name),
        ),
      )
    : rubricLabels
  const [verdict, setVerdict] = useState<HumanReview['verdict']>(
    result.review?.verdict || 'uncertain',
  )
  const [comment, setComment] = useState(result.review?.comment || '')
  const [questionReviews, setQuestionReviews] = useState<QuestionReview[]>(() =>
    questions.map((question) => {
      const questionId = textValue(question.id || question.question_id)
      const previous = result.review?.question_reviews?.find(
        (review) => review.question_id === questionId,
      )
      return {
        question_id: questionId,
        decisions: Object.fromEntries(
          Object.keys(reviewLabels).map((field) => [field, previous?.decisions[field] ?? null]),
        ),
        comment: previous?.comment || '',
      }
    }),
  )
  const save = useMutation({
    mutationFn: () =>
      evaluationApi.review(runId, result.result_id, {
        expected_revision: result.review_revision,
        verdict,
        comment: comment.trim(),
        ...(questionReviews.length ? { question_reviews: questionReviews } : {}),
      }),
    onSuccess: onSaved,
  })
  const pack = objectValue(isPractice ? practice.evidence_pack : artifact.evidence_pack)
  const trace = objectValue(artifact.trace)
  const metricEntries = Object.entries(result.metrics || {})
  const primaryMetrics = metricEntries.filter(([name]) => isBasicMetric(result.case_type, name))
  const otherMetrics = metricEntries.filter(([name]) => !isBasicMetric(result.case_type, name))
  const hasUnknown = Object.values(result.metrics || {}).some(
    (metric) =>
      ['unknown', 'error', 'pending'].includes(metric.status || '') ||
      (metric.unknown_count || 0) > 0,
  )
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!save.isPending) save.mutate()
  }
  return (
    <section className="sample-inspector">
      <div className="section-line">
        <div>
          <p className="eyebrow">SAMPLE INSPECTOR</p>
          <h2>{result.sample_id}</h2>
        </div>
        <StatusBadge status={result.status} />
      </div>
      <p className="sample-query">{samplePrompt(result.sample)}</p>
      {result.error_code && (
        <div className="notice warning">
          失败类型：{failureLabels[failureCategory(result.error_code)]} · {result.error_code}
        </div>
      )}
      {isGrading && (
        <section className="card stack-form" aria-label="判分与独立参考">
          <h3>判分与独立参考</h3>
          <div className="manifest-summary">
            <span>
              题型：
              {result.sample.question_type
                ? practiceTypeLabels[result.sample.question_type]
                : '未知'}
            </span>
            <span>判分方式：{gradeSourceLabels[textValue(assessment.source)] || '未知'}</span>
            <span>判分状态：{gradeStatusLabels[textValue(assessment.status)] || '未知'}</span>
            <span>
              确认标记：
              {assessment.confirmation === 'confirmed'
                ? '已确认'
                : assessment.confirmation === 'provisional'
                  ? '暂定，待复核'
                  : '未知'}
            </span>
            <span data-testid="predicted-grade-score">
              被测得分：{formatGradeScore(assessment.score, assessment.status)}
            </span>
            <span data-testid="reference-grade-score">
              独立参考得分：
              {formatGradeScore(
                result.sample.reference_grade?.score,
                result.sample.reference_grade?.status,
              )}
            </span>
            <span>
              参考来源：
              {result.sample.reference_grade?.provenance === 'human'
                ? '人工参考'
                : result.sample.reference_grade?.provenance === 'synthetic_fixture'
                  ? '工程夹具'
                  : '未提供'}
            </span>
            <span>
              预期状态：{gradeStatusLabels[result.sample.expected_grade_status || ''] || '未知'}
            </span>
          </div>
          {assessment.source === 'model' && assessment.confirmation !== 'confirmed' && (
            <p className="notice warning">模型判分暂定，待复核；分数接近参考值不表示已确认。</p>
          )}
          <p className="tiny muted">缺失分数与技术失败不表示答错。本评测不更新学习记录。</p>
          {typeof assessment.feedback === 'string' && assessment.feedback && (
            <p>{assessment.feedback}</p>
          )}
        </section>
      )}
      <div className="inspector-grid">
        <section>
          <h3>参考真值 / Gold</h3>
          <JsonView
            value={{
              expected_outcome: result.sample.expected_outcome,
              ...(isQa
                ? {
                    expected_answer_status: result.sample.expected_answer_status,
                    expected_error_code: result.sample.expected_error_code,
                    history: result.sample.history,
                  }
                : {}),
              ...(isPractice
                ? {
                    spec: result.sample.spec,
                    generation_rubric: result.sample.generation_rubric,
                    expected_error_code: result.sample.expected_error_code,
                  }
                : {}),
              ...(isGrading
                ? {
                    expected_grade_status: result.sample.expected_grade_status,
                    expected_error_code: result.sample.expected_error_code,
                    reference_grade: result.sample.reference_grade,
                  }
                : {}),
              gold_evidence_groups: result.sample.gold_evidence_groups,
              ranking_labels: result.sample.ranking_labels,
              expected_objectives: result.sample.expected_objectives,
              question_rubrics: result.sample.question_rubrics,
              annotation: result.sample.annotation,
            }}
          />
        </section>
        <section>
          <h3>{isGrading ? '固定题目与作答' : '召回候选'}</h3>
          <JsonView
            value={
              isGrading
                ? {
                    question: result.sample.question,
                    answer: result.sample.answer,
                    question_version: result.sample.question_version,
                    rubric_hash: result.sample.rubric_hash,
                    response_hash: result.sample.response_hash,
                  }
                : artifact.candidates ||
                  artifact.retrieval_candidates ||
                  trace.candidates ||
                  pack.candidates ||
                  artifact.evidence ||
                  pack.evidence
            }
          />
        </section>
        <section>
          <h3>{isGrading ? '给定证据与引用' : '最终上下文'}</h3>
          <JsonView
            value={
              isGrading
                ? {
                    source_refs: result.sample.source_refs,
                    citation_refs: objectValue(result.sample.question).citation_refs,
                    evidence_refs: assessment.evidence_refs,
                  }
                : artifact.final_context || artifact.context || pack.evidence || artifact.evidence
            }
          />
        </section>
        <section>
          <h3>{isQa ? '问答、引用与校验' : isGrading ? '判分依据与版本' : '题目、引用与校验'}</h3>
          {isQa && artifact.answer_status != null && (
            <p>
              回答状态：
              {answerStatusLabels[textValue(artifact.answer_status)] ||
                textValue(artifact.answer_status)}
            </p>
          )}
          <JsonView
            value={
              isGrading
                ? grade
                : isPractice
                  ? practice
                  : isQa
                    ? {
                        answer_status: artifact.answer_status,
                        blocks: artifact.blocks,
                        retrieval_query: artifact.retrieval_query,
                        trace: artifact.trace,
                      }
                    : artifact.questions
                      ? {
                          questions: artifact.questions,
                          validation: artifact.validation,
                          citation_refs: artifact.citation_refs,
                        }
                      : artifact.output || artifact
            }
          />
        </section>
      </div>
      <section className="sample-metrics">
        <div className="section-line">
          <h3>自动评分</h3>
          {hasUnknown && <span className="badge status-unknown">评分待裁决</span>}
        </div>
        <p className="tiny muted">自动估计与人工判定分别记录；缺失值和评分器故障不记为零分。</p>
        <div className="metric-cards">
          {primaryMetrics.map(([name, metric]) => (
            <MetricCard key={name} name={name} metric={metric} />
          ))}
        </div>
        {!!otherMetrics.length && (
          <details className="technical-details">
            <summary>其他指标与分母（{otherMetrics.length}）</summary>
            <div className="metric-cards">
              {otherMetrics.map(([name, metric]) => (
                <MetricCard key={name} name={name} metric={metric} />
              ))}
            </div>
          </details>
        )}
        {!Object.keys(result.metrics || {}).length && <p className="muted tiny">尚无评分结果。</p>}
      </section>
      <form className="human-review" onSubmit={submit}>
        <div className="section-line">
          <h3>人工复核</h3>
          {result.review && (
            <span className="badge">已有人工记录 · revision {result.review_revision}</span>
          )}
        </div>
        <p className="tiny muted">请核对原文、真值与输出，再记录判定及争议理由。</p>
        {!!questionReviews.length && (
          <div className="question-reviews">
            <p className="tiny muted">逐题判定保留未判定项。整体“通过”不会代填这些语义指标。</p>
            {questionReviews.map((review, index) => (
              <details className="question-review" key={review.question_id} open>
                <summary>
                  第 {index + 1} 题：{textValue(questions[index].stem)}
                </summary>
                <div className="rubric-fields">
                  {Object.entries(reviewLabels).map(([field, label]) => (
                    <label key={field}>
                      {label}
                      <select
                        aria-label={`第 ${index + 1} 题 · ${label}`}
                        value={
                          review.decisions[field] == null
                            ? 'unknown'
                            : String(review.decisions[field])
                        }
                        onChange={(event) =>
                          setQuestionReviews((current) =>
                            current.map((item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    decisions: {
                                      ...item.decisions,
                                      [field]:
                                        event.target.value === 'unknown'
                                          ? null
                                          : event.target.value === 'true',
                                    },
                                  }
                                : item,
                            ),
                          )
                        }
                      >
                        <option value="unknown">未判定</option>
                        <option value="true">符合</option>
                        <option value="false">不符合</option>
                      </select>
                    </label>
                  ))}
                </div>
                <label>
                  本题依据与争议
                  <textarea
                    rows={2}
                    maxLength={2000}
                    value={review.comment || ''}
                    aria-label={`第 ${index + 1} 题 · 复核依据`}
                    onChange={(event) =>
                      setQuestionReviews((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, comment: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
              </details>
            ))}
          </div>
        )}
        <div className="review-fields">
          <label>
            人工判定
            <select
              value={verdict}
              onChange={(event) => setVerdict(event.target.value as HumanReview['verdict'])}
            >
              <option value="uncertain">待裁决 / 有争议</option>
              <option value="pass">通过</option>
              <option value="fail">不通过</option>
            </select>
          </label>
          <label>
            复核理由
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
              maxLength={2000}
              required
              placeholder="写明支持判定的证据与限制。"
            />
          </label>
        </div>
        <ErrorNotice error={save.error} />
        {save.isSuccess && (
          <p className="saved-notice" role="status">
            <CheckCircle2 size={15} />
            人工复核已保存
          </p>
        )}
        <button
          className="button primary button-small"
          disabled={save.isPending || !comment.trim()}
        >
          <Save size={15} />
          {save.isPending ? '正在保存…' : '保存复核'}
        </button>
      </form>
      <details className="technical-details">
        <summary>完整样本、运行工件与用量</summary>
        <JsonView
          value={{ sample: result.sample, artifact: result.artifact, review: result.review }}
        />
      </details>
    </section>
  )
}
