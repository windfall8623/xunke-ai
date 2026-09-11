import type { Metric } from '../features/evaluation/metrics'
import type { ApiSchemas } from './api'

export type JsonObject = Record<string, unknown>
export type EvaluationCaseType = ApiSchemas['EvalSample']['case_type']
export type EvaluationPracticeQuestion = ApiSchemas['AnswerGradingSample']['question']
export interface DatasetSample extends JsonObject {
  sample_id: string
  case_type: EvaluationCaseType
  split?: string
  query?: string
  user_input?: string
  question?: string | EvaluationPracticeQuestion
  spec?: ApiSchemas['PracticeSpec']
  generation_rubric?: ApiSchemas['PracticeGenerationRubric']
  question_type?: ApiSchemas['AnswerGradingSample']['question_type']
  question_version?: string
  rubric_hash?: string
  answer?: ApiSchemas['AnswerGradingSample']['answer']
  response_hash?: string
  expected_grade_status?: ApiSchemas['AnswerGradingSample']['expected_grade_status']
  reference_grade?: ApiSchemas['ReferenceGrade'] | null
  history?: Array<{ question: string; answer: string }>
  expected_answer_status?: ApiSchemas['QaAnswerView']['answer_status'] | null
  expected_error_code?: string | null
  family_id?: string
  family_ids?: string[]
  tags?: string[]
  source_refs?: JsonObject[]
  gold_evidence_groups?: unknown[]
}
export interface DatasetVersion extends Omit<ApiSchemas['DatasetView'], 'samples'> {
  samples?: DatasetSample[]
}
export interface Pipeline {
  pipeline_id: string
  name: string
  description?: string
  index_profile_id?: string
  config: JsonObject
}
export type EvalRun = ApiSchemas['RunView'] & {
  can_resume?: boolean
}
export interface HumanReview {
  verdict: 'pass' | 'fail' | 'uncertain'
  comment: string
  reviewer_id?: number | string
  reviewed_at?: string
  question_reviews?: QuestionReview[]
}
export interface QuestionReview {
  question_id: string
  decisions: Record<string, boolean | null>
  comment?: string
}
export interface EvalResult
  extends Omit<ApiSchemas['ResultView'], 'sample' | 'metrics' | 'review'> {
  sample: DatasetSample
  metrics?: Record<string, Metric & { unknown_count?: number }> | null
  review?: HumanReview | null
}
export interface ComparisonMetric {
  baseline: Metric
  candidate: Metric
  delta: number | null
  confidence_interval?: [number, number] | null
  unit?: string
  sample_count?: number
  status?: string
}
export interface Comparison {
  comparison_eligible: boolean
  exploratory: boolean
  reason?: string
  baseline_run_id: string
  candidate_run_id: string
  metrics: Record<string, ComparisonMetric>
  sample_count: number
  cluster_count: number
}
export type SourceExcerpt = ApiSchemas['SourceExcerptView']
export interface FeedbackCandidateRequest {
  name: string
  redacted_request: string
  question_count: number
  dataset_id?: string
}
export interface FeedbackView {
  feedback_id: string
  quiz_id: string
  question_id: string
  reason: string
  comment: string
  allow_evaluation_use: boolean
  status: string
  revision: number
  created_at: string
  review: {
    verdict: 'approved' | 'rejected' | 'needs_changes'
    comment: string
    reviewer_id: string | number
    reviewed_at: string
  } | null
  promotion: {
    state: string
    request?: FeedbackCandidateRequest
    documents?: JsonObject[]
    dataset_id?: string
    dataset_version?: number
  } | null
  access_scope: 'owner_only'
}
export interface FeedbackPromotion {
  status: 'preparing' | 'promoted'
  feedback: FeedbackView
  documents: import('./api').DocumentItem[]
  dataset_id?: string
  dataset_version?: number
}
