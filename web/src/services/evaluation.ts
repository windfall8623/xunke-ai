import { request, requestDownload } from './http'
import type { ApiSchemas, DocumentItem, Page } from '../types/api'
import type {
  Comparison,
  DatasetSample,
  DatasetVersion,
  EvalResult,
  EvalRun,
  FeedbackCandidateRequest,
  FeedbackPromotion,
  FeedbackView,
  HumanReview,
  JsonObject,
  Pipeline,
  SourceExcerpt,
} from '../types/evaluation'

const id = encodeURIComponent
export const evaluationApi = {
  feedback: (signal?: AbortSignal) => request<Page<FeedbackView>>('/eval/feedback', { signal }),
  reviewFeedback: (
    feedbackId: string,
    data: {
      expected_revision: number
      verdict: 'approved' | 'rejected' | 'needs_changes'
      comment: string
    },
  ) => request<FeedbackView>(`/eval/feedback/${id(feedbackId)}/review`, { method: 'PUT', data }),
  promoteFeedback: (
    feedbackId: string,
    data: FeedbackCandidateRequest & { expected_revision: number },
  ) =>
    request<FeedbackPromotion>(`/eval/feedback/${id(feedbackId)}/promote`, {
      method: 'POST',
      data,
    }),
  documents: (signal?: AbortSignal) => request<Page<DocumentItem>>('/eval/documents', { signal }),
  uploadDocument: (file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<DocumentItem>('/eval/documents', { method: 'POST', data, timeoutMs: 120_000 })
  },
  reindexDocument: (docId: string, indexProfile: string) =>
    request<DocumentItem>(`/eval/documents/${id(docId)}/reindex`, {
      method: 'POST',
      data: { index_profile_id: indexProfile },
    }),
  deleteDocument: (docId: string) =>
    request<ApiSchemas['DocumentDeletionView']>(`/eval/documents/${id(docId)}`, {
      method: 'DELETE',
    }),
  datasets: (signal?: AbortSignal) => request<Page<DatasetVersion>>('/eval/datasets', { signal }),
  dataset: (datasetId: string, version: number, signal?: AbortSignal) =>
    request<DatasetVersion>(`/eval/datasets/${id(datasetId)}/versions/${version}`, { signal }),
  createDataset: (data: {
    name: string
    manifest: JsonObject
    samples: DatasetSample[]
    dataset_id?: string
  }) => request<DatasetVersion>('/eval/datasets', { method: 'POST', data }),
  patchDataset: (
    datasetId: string,
    version: number,
    data: { revision: number; name?: string; manifest?: JsonObject; samples?: DatasetSample[] },
  ) =>
    request<DatasetVersion>(`/eval/datasets/${id(datasetId)}/versions/${version}`, {
      method: 'PATCH',
      data,
    }),
  freeze: (
    datasetId: string,
    version: number,
    revision: number,
    checklist: Record<string, boolean>,
  ) =>
    request<DatasetVersion>(`/eval/datasets/${id(datasetId)}/versions/${version}/freeze`, {
      method: 'POST',
      data: { expected_revision: revision, checklist },
    }),
  reviewSample: (
    datasetId: string,
    version: number,
    sampleId: string,
    data: { expected_revision: number; verdict: 'approved' | 'needs_changes'; comment: string },
  ) =>
    request<DatasetVersion>(
      `/eval/datasets/${id(datasetId)}/versions/${version}/samples/${id(sampleId)}/review`,
      { method: 'POST', data },
    ),
  revoke: (datasetId: string, version: number) =>
    request<null>(`/eval/datasets/${id(datasetId)}/versions/${version}`, { method: 'DELETE' }),
  pipelines: (signal?: AbortSignal) => request<Page<Pipeline>>('/eval/pipelines', { signal }),
  judges: (signal?: AbortSignal) =>
    request<ApiSchemas['JudgeProfileList']>('/eval/judges', { signal }),
  runs: (signal?: AbortSignal) => request<Page<EvalRun>>('/eval/runs', { signal }),
  estimateRun: (data: Omit<ApiSchemas['RunCreate'], 'max_cost_cny'>, signal?: AbortSignal) =>
    request<ApiSchemas['RunCostPreview']>(
      `/eval/runs/estimate?${new URLSearchParams({
        dataset_id: data.dataset_id,
        dataset_version: String(data.dataset_version),
        pipeline_id: data.pipeline_id,
        judge_profile_id: data.judge_profile_id ?? 'deterministic-v1',
        repeat_count: String(data.repeat_count ?? 1),
      })}`,
      { signal },
    ),
  createRun: (data: ApiSchemas['RunCreate'], key: string) =>
    request<EvalRun>('/eval/runs', { method: 'POST', data, idempotencyKey: key }),
  run: (runId: string, signal?: AbortSignal) =>
    request<EvalRun>(`/eval/runs/${id(runId)}`, { signal }),
  results: (runId: string, signal?: AbortSignal) =>
    request<Page<EvalResult>>(`/eval/runs/${id(runId)}/results`, { signal }),
  cancel: (runId: string) => request<EvalRun>(`/eval/runs/${id(runId)}/cancel`, { method: 'POST' }),
  resume: (runId: string) => request<EvalRun>(`/eval/runs/${id(runId)}/resume`, { method: 'POST' }),
  review: (runId: string, resultId: string, data: HumanReview & { expected_revision: number }) =>
    request<Pick<EvalResult, 'result_id' | 'review' | 'review_revision'>>(
      `/eval/runs/${id(runId)}/results/${id(resultId)}/review`,
      {
        method: 'PUT',
        data,
      },
    ),
  compare: (
    baseline: string,
    candidate: string,
    exploratory: boolean,
    group?: string,
    signal?: AbortSignal,
  ) =>
    request<Comparison>(
      `/eval/compare?${new URLSearchParams({ baseline_run_id: baseline, candidate_run_id: candidate, ...(exploratory ? { exploratory: 'true' } : {}), ...(group ? { group } : {}) })}`,
      { signal },
    ),
  exportRun: (runId: string, format: string) =>
    requestDownload(
      `/eval/runs/${id(runId)}/export?${new URLSearchParams({ format })}`,
      `evaluation-${runId}.${format === 'markdown' ? 'md' : format}`,
    ),
  source: (docId: string, query: Record<string, string>, signal?: AbortSignal) =>
    request<SourceExcerpt>(`/eval/documents/${id(docId)}/source?${new URLSearchParams(query)}`, {
      signal,
    }),
}
