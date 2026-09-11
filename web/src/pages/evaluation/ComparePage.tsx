import { useQuery } from '@tanstack/react-query'
import { GitCompareArrows } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { MetricComparison } from '../../features/evaluation/MetricComparison'
import { WorkbenchNav, textValue } from '../../features/evaluation/WorkbenchNav'
import { evaluationApi } from '../../services/evaluation'

export function ComparePage() {
  const identity = useIdentityKey()
  const [params, setParams] = useSearchParams()
  const [baseline, setBaseline] = useState(params.get('baseline') || '')
  const [candidate, setCandidate] = useState(params.get('candidate') || '')
  const [exploratory, setExploratory] = useState(params.get('exploratory') === 'true')
  const [group, setGroup] = useState(params.get('group') || 'all')
  const left = params.get('baseline') || ''
  const right = params.get('candidate') || ''
  const runs = useQuery({
    queryKey: [identity, 'eval-runs'],
    queryFn: ({ signal }) => evaluationApi.runs(signal),
  })
  const comparison = useQuery({
    queryKey: [
      identity,
      'eval-compare',
      left,
      right,
      params.get('exploratory'),
      params.get('group'),
    ],
    queryFn: ({ signal }) =>
      evaluationApi.compare(
        left,
        right,
        params.get('exploratory') === 'true',
        params.get('group') || undefined,
        signal,
      ),
    enabled: !!left && !!right && left !== right,
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (baseline && candidate && baseline !== candidate)
      setParams({
        baseline,
        candidate,
        ...(exploratory ? { exploratory: 'true' } : {}),
        ...(group !== 'all' ? { group } : {}),
      })
  }
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <PageHeading
        eyebrow="COMPARE WITH CONTEXT"
        title="方案对比"
        description="同一批样本，观察质量、成本与不确定性。"
      />
      <form className="card compare-form" onSubmit={submit}>
        <div className="comparison-selectors">
          <label>
            基线运行
            <select value={baseline} required onChange={(event) => setBaseline(event.target.value)}>
              <option value="">选择基线</option>
              {runs.data?.items.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {textValue(run.pipeline_id ?? run.manifest.pipeline_id)} · {run.run_id}
                </option>
              ))}
            </select>
          </label>
          <span className="compare-icon">
            <GitCompareArrows size={22} />
          </span>
          <label>
            候选运行
            <select
              value={candidate}
              required
              onChange={(event) => setCandidate(event.target.value)}
            >
              <option value="">选择候选</option>
              {runs.data?.items.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {textValue(run.pipeline_id ?? run.manifest.pipeline_id)} · {run.run_id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="compare-controls">
          <label>
            样本分组
            <select value={group} onChange={(event) => setGroup(event.target.value)}>
              <option value="all">全部样本</option>
              <option value="pdf">PDF 资料</option>
              <option value="chinese_terms">中文术语</option>
              <option value="unanswerable">无答案样本</option>
            </select>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={exploratory}
              onChange={(event) => setExploratory(event.target.checked)}
            />
            <span>
              允许探索性对照<small>不用于正式发布判断</small>
            </span>
          </label>
          <button
            className="button primary"
            disabled={!baseline || !candidate || baseline === candidate || comparison.isFetching}
          >
            对比运行
          </button>
        </div>
        <ErrorNotice
          error={runs.error}
          onRetry={() => {
            void runs.refetch()
          }}
        />
      </form>
      <ErrorNotice
        error={comparison.error}
        onRetry={() => {
          void comparison.refetch()
        }}
      />
      {!left || !right ? (
        <section className="card">
          <EmptyState title="选择两次运行开始比较">
            优先使用相同数据集版本、指标协议与缓存条件。
          </EmptyState>
        </section>
      ) : comparison.isPending ? (
        <Loading>正在读取配对结果…</Loading>
      ) : (
        comparison.data && (
          <>
            <div
              className={`notice ${comparison.data.comparison_eligible && !comparison.data.exploratory ? 'success' : 'warning'}`}
            >
              <div>
                <strong data-testid="release-status">
                  {comparison.data.exploratory
                    ? '探索性对照'
                    : comparison.data.comparison_eligible
                      ? '具备正式比较条件'
                      : '结果尚不支持正式判断'}
                </strong>
                <p>{comparison.data.reason || '请结合区间、样本量、失败数与人工复核评估差异。'}</p>
              </div>
            </div>
            <MetricComparison comparison={comparison.data} />
          </>
        )
      )}
    </div>
  )
}
