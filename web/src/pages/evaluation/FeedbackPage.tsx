import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, MessageSquare, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading, StatusBadge } from '../../components/ui'
import { WorkbenchNav } from '../../features/evaluation/WorkbenchNav'
import { evaluationApi } from '../../services/evaluation'
import type { Page } from '../../types/api'
import type { DatasetVersion, FeedbackCandidateRequest, FeedbackView } from '../../types/evaluation'

const reasons: Record<string, string> = {
  incorrect_answer: '答案有误',
  unsupported_explanation: '解析无依据',
  citation_mismatch: '引用不符',
  duplicate: '题目重复',
  other: '其他问题',
}

export function FeedbackPage() {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [selected, setSelected] = useState('')
  const key = [identity, 'eval-feedback']
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => evaluationApi.feedback(signal),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === 'preparing') ? 4000 : false,
    refetchIntervalInBackground: false,
  })
  const datasets = useQuery({
    queryKey: [identity, 'eval-datasets'],
    queryFn: ({ signal }) => evaluationApi.datasets(signal),
  })
  const current =
    query.data?.items.find((item) => item.feedback_id === selected) || query.data?.items[0]
  function saved(value: FeedbackView) {
    client.setQueryData<Page<FeedbackView>>(key, (previous) =>
      previous
        ? {
            ...previous,
            items: previous.items.map((item) =>
              item.feedback_id === value.feedback_id ? value : item,
            ),
          }
        : previous,
    )
    void client.invalidateQueries({ queryKey: key })
    void client.invalidateQueries({ queryKey: [identity, 'eval-datasets'] })
  }
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <PageHeading
        title="反馈与回归候选"
        description="复核已发现的问题，经过授权与脱敏后建立新的评测候选。"
        action={
          <button
            className="button secondary"
            disabled={query.isFetching}
            onClick={() => {
              void query.refetch()
            }}
          >
            <RefreshCw size={16} />
            刷新
          </button>
        }
      />
      <div className="notice evaluation-note">
        <ShieldCheck size={20} />
        <p>这里只显示本人有权处理的反馈。反馈、答错记录与投诉不会自动成为 Gold。</p>
      </div>
      <ErrorNotice error={query.error || datasets.error} />
      {query.isPending ? (
        <Loading />
      ) : query.error ? null : !current ? (
        <section className="card">
          <EmptyState title="暂无可处理的反馈">在本人练习中提交的问题会显示在这里。</EmptyState>
        </section>
      ) : (
        <div className="results-layout">
          <nav className="sample-list card" aria-label="选择反馈">
            {query.data?.items.map((item) => (
              <button
                key={item.feedback_id}
                onClick={() => setSelected(item.feedback_id)}
                className={item.feedback_id === current.feedback_id ? 'selected' : ''}
              >
                <strong>{reasons[item.reason] || item.reason}</strong>
                <span>{item.question_id}</span>
                <StatusBadge status={item.status} />
              </button>
            ))}
          </nav>
          <section className="card inspector-card">
            <FeedbackEditor
              key={`${current.feedback_id}:${current.revision}:${current.status}`}
              feedback={current}
              datasets={datasets.data?.items || []}
              onSaved={saved}
            />
          </section>
        </div>
      )}
    </div>
  )
}

function FeedbackEditor({
  feedback,
  datasets,
  onSaved,
}: {
  feedback: FeedbackView
  datasets: DatasetVersion[]
  onSaved: (value: FeedbackView) => void
}) {
  const [verdict, setVerdict] = useState<'approved' | 'rejected' | 'needs_changes'>(
    feedback.review?.verdict || 'needs_changes',
  )
  const [comment, setComment] = useState(feedback.review?.comment || '')
  const [parameters, setParameters] = useState<FeedbackCandidateRequest>(
    feedback.promotion?.request || {
      name: '反馈回归候选',
      redacted_request: '',
      question_count: 3,
    },
  )
  const preparing = feedback.status === 'preparing'
  const promoted = feedback.status === 'promoted'
  const review = useMutation({
    mutationFn: () =>
      evaluationApi.reviewFeedback(feedback.feedback_id, {
        expected_revision: feedback.revision,
        verdict,
        comment: comment.trim(),
      }),
    onSuccess: onSaved,
  })
  const promotion = useMutation({
    mutationFn: () =>
      evaluationApi.promoteFeedback(feedback.feedback_id, {
        ...parameters,
        expected_revision: feedback.revision,
      }),
    onSuccess: (result) => onSaved(result.feedback),
  })
  function saveReview(event: FormEvent) {
    event.preventDefault()
    if (comment.trim() && !review.isPending) review.mutate()
  }
  function promote(event: FormEvent) {
    event.preventDefault()
    if (!promotion.isPending) promotion.mutate()
  }
  return (
    <div className="sample-inspector">
      <div className="section-line">
        <h2>
          <MessageSquare size={18} /> {reasons[feedback.reason] || feedback.reason}
        </h2>
        <StatusBadge status={feedback.status} />
      </div>
      <p className="sample-query">{feedback.comment || '未填写补充说明'}</p>
      <Link
        className="text-link"
        to={`/quizzes/${encodeURIComponent(feedback.quiz_id)}?question=${encodeURIComponent(feedback.question_id)}`}
      >
        核对原题与引用
        <ArrowRight size={14} />
      </Link>
      <p>
        <span
          className={`badge ${feedback.allow_evaluation_use ? 'status-ready' : 'status-unknown'}`}
        >
          {feedback.allow_evaluation_use ? '已获准用于评测' : '未获准用于评测'}
        </span>
      </p>
      {!preparing && !promoted && (
        <form className="stack-form human-review" onSubmit={saveReview}>
          <h3>人工核对反馈</h3>
          <label>
            反馈判定
            <select
              value={verdict}
              onChange={(event) => setVerdict(event.target.value as typeof verdict)}
            >
              <option value="needs_changes">需补充或仍有争议</option>
              <option value="approved">已核实，接受反馈</option>
              <option value="rejected">未发现所述问题</option>
            </select>
          </label>
          <label>
            反馈复核理由
            <textarea
              required
              rows={3}
              maxLength={2000}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
          </label>
          <ErrorNotice error={review.error} />
          <button className="button secondary" disabled={review.isPending || !comment.trim()}>
            保存反馈复核
          </button>
        </form>
      )}
      {feedback.allow_evaluation_use && ['approved', 'preparing'].includes(feedback.status) && (
        <form className="stack-form human-review" onSubmit={promote}>
          <h3>建立待标注的回归候选</h3>
          <p className="tiny muted">
            所需资料会复制至独立评测空间并保留来源授权关系。候选需要补齐
            Gold、重新人审、冻结后才可运行；已有冻结版本保持只读。
          </p>
          <fieldset disabled={preparing || promotion.isPending} className="candidate-fields">
            <label>
              目标数据集
              <select
                value={parameters.dataset_id || ''}
                onChange={(event) =>
                  setParameters((value) => {
                    const { dataset_id: _, ...rest } = value
                    return event.target.value ? { ...rest, dataset_id: event.target.value } : rest
                  })
                }
              >
                <option value="">创建新数据集</option>
                {[
                  ...new Map(
                    datasets
                      .filter((item) => item.status !== 'revoked')
                      .map((item) => [item.dataset_id, item]),
                  ).values(),
                ].map((item) => (
                  <option key={item.dataset_id} value={item.dataset_id}>
                    {item.name} · 建立新版本
                  </option>
                ))}
              </select>
            </label>
            <label>
              候选版本名称
              <input
                value={parameters.name}
                onChange={(event) =>
                  setParameters((value) => ({ ...value, name: event.target.value }))
                }
                required
                maxLength={200}
              />
            </label>
            <label>
              脱敏后的学习目标
              <textarea
                value={parameters.redacted_request}
                onChange={(event) =>
                  setParameters((value) => ({ ...value, redacted_request: event.target.value }))
                }
                required
                maxLength={2000}
                rows={3}
                placeholder="保留需检验的学习目标，移除个人资料与无关私密信息。"
              />
            </label>
            <label>
              请求题量
              <select
                value={parameters.question_count}
                onChange={(event) =>
                  setParameters((value) => ({
                    ...value,
                    question_count: Number(event.target.value),
                  }))
                }
              >
                {Array.from({ length: 8 }, (_, index) => index + 3).map((count) => (
                  <option key={count} value={count}>
                    {count} 题
                  </option>
                ))}
              </select>
            </label>
          </fieldset>
          {preparing && (
            <div className="notice warning">
              <p>评测资料正在准备。处理完成后，使用已保存的同一组参数继续建立候选。</p>
            </div>
          )}
          {feedback.promotion?.documents?.map((document, index) => (
            <p key={String(document.doc_id || index)} className="tiny muted">
              {String(document.file_name || document.doc_id || '评测资料')} ·{' '}
              <StatusBadge status={String(document.status || 'processing')} />
            </p>
          ))}
          <ErrorNotice error={promotion.error} />
          <button
            className="button primary"
            disabled={
              promotion.isPending ||
              !parameters.name.trim() ||
              !parameters.redacted_request.trim() ||
              (preparing && !feedback.promotion?.request)
            }
          >
            {promotion.isPending ? '正在处理…' : preparing ? '继续建立候选' : '建立评测候选'}
            <ArrowRight size={16} />
          </button>
        </form>
      )}
      {promoted && feedback.promotion?.dataset_id && (
        <div className="notice success">
          <div>
            <p>候选已建立，标签仍需人工核对。</p>
            <Link
              className="text-link"
              to={`/evaluations/datasets/${encodeURIComponent(feedback.promotion.dataset_id)}/versions/${feedback.promotion.dataset_version}`}
            >
              打开候选数据集
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
