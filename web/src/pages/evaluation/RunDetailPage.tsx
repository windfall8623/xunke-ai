import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, Pause, Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading, StatusBadge } from '../../components/ui'
import { SampleInspector } from '../../features/evaluation/SampleInspector'
import { caseLabels } from '../../features/evaluation/dataset'
import {
  JsonView,
  WorkbenchNav,
  failureCategory,
  failureLabels,
  textValue,
} from '../../features/evaluation/WorkbenchNav'
import { evaluationApi } from '../../services/evaluation'
import { ApiError, saveDownload } from '../../services/http'

const activeStates = ['queued', 'running', 'scoring', 'pending']
export function RunDetailPage() {
  const canRun = useAuth().user?.role === 'admin'
  const { runId = '' } = useParams()
  const identity = useIdentityKey()
  const [selected, setSelected] = useState('')
  const [failure, setFailure] = useState('all')
  const [exportFormat, setExportFormat] = useState('jsonl')
  const run = useQuery({
    queryKey: [identity, 'eval-run', runId],
    queryFn: ({ signal }) => evaluationApi.run(runId, signal),
    refetchInterval: (query) =>
      activeStates.includes(query.state.data?.status || '') ? 3000 : false,
    refetchIntervalInBackground: false,
  })
  const results = useQuery({
    queryKey: [identity, 'eval-results', runId],
    queryFn: ({ signal }) => evaluationApi.results(runId, signal),
    refetchInterval: activeStates.includes(run.data?.status || '') ? 3500 : false,
    refetchIntervalInBackground: false,
  })
  const refresh = () => {
    void run.refetch()
    void results.refetch()
  }
  const action = useMutation({
    mutationFn: (kind: 'cancel' | 'resume') => {
      if (kind === 'resume' && !canRun) throw new Error('恢复评测运行需要管理员权限。')
      return kind === 'cancel' ? evaluationApi.cancel(runId) : evaluationApi.resume(runId)
    },
    onSuccess: refresh,
  })
  const exportRun = useMutation({
    mutationFn: () => evaluationApi.exportRun(runId, exportFormat),
    onSuccess: saveDownload,
  })
  const unavailable = [run.error, results.error].some(
    (error) => error instanceof ApiError && [403, 404, 410].includes(error.status),
  )
  const filtered = (unavailable ? [] : results.data?.items || []).filter(
    (result) => failure === 'all' || failureCategory(result.error_code) === failure,
  )
  const current = filtered.find((item) => item.result_id === selected) || filtered[0]
  const data = run.data
  const unknown =
    results.data?.items.filter((result) =>
      Object.values(result.metrics || {}).some(
        (metric) =>
          ['error', 'unknown', 'pending'].includes(metric.status || '') ||
          (metric.unknown_count || 0) > 0,
      ),
    ).length || 0
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <Link to="/evaluations/runs" className="back-link">
        <ArrowLeft size={15} />
        全部运行
      </Link>
      <PageHeading
        title="运行详情"
        description={runId}
        action={
          <div className="button-row">
            <button className="button secondary button-small" onClick={refresh}>
              <RefreshCw size={15} />
              刷新
            </button>
            {data && activeStates.includes(data.status) && (
              <button
                className="button secondary button-small"
                disabled={action.isPending}
                onClick={() => action.mutate('cancel')}
              >
                <Pause size={15} />
                取消运行
              </button>
            )}
            {canRun && data &&
              (data.can_resume === true ||
                (data.can_resume !== false && ['failed', 'cancelled'].includes(data.status))) && (
                <button
                  className="button secondary button-small"
                  disabled={action.isPending}
                  onClick={() => action.mutate('resume')}
                >
                  <Play size={15} />
                  恢复运行
                </button>
              )}
          </div>
        }
      />
      <ErrorNotice error={run.error || action.error} onRetry={refresh} />
      {run.isPending ? (
        <Loading />
      ) : (
        data && (
          <>
            <div className="run-status-line">
              <StatusBadge status={data.status} />
              <span
                data-testid="release-status"
                className={`badge ${data.comparison_eligible ? 'status-ready' : 'status-unknown'}`}
              >
                {data.comparison_eligible
                  ? '具备正式比较条件 · 尚需对照'
                  : activeStates.includes(data.status)
                    ? '评测进行中'
                    : '未达到正式比较条件'}
              </span>
              {unknown > 0 && <span className="badge status-unknown">评分待裁决</span>}
              {data.stop_reason && (
                <span className="badge status-incomplete">停止原因：{data.stop_reason}</span>
              )}
            </div>
            <p className="tiny muted">
              运行完成表示处理流程结束。先检查逐样本结果、待复核项与实际费用；小样本结果仅供诊断。
            </p>
            {!!data.ineligibility_reasons?.length && (
              <p className="notice warning">当前限制：{data.ineligibility_reasons.join('；')}</p>
            )}
            <div className="run-progress-cards">
              {[
                ['计划', data.progress.total],
                ['已评分', data.progress.completed],
                ['评分中', data.progress.scoring],
                ['执行失败', data.progress.prediction_failed ?? '—'],
                ['评分错误', data.progress.failed],
                ['等待', data.progress.pending],
                ['待裁决', unknown],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <details className="card run-manifest">
              <summary>本次运行配置与预算</summary>
              <div className="manifest-summary">
                <span>方案：{textValue(data.pipeline_id ?? data.manifest.pipeline_id)}</span>
                <span>评分：{textValue(data.manifest.judge_profile_id, '未记录')}</span>
                <span>
                  最大预算：¥ {textValue(data.max_cost_cny ?? data.manifest.max_cost_cny)}
                </span>
                <span>已记录费用：¥ {textValue(data.spent_cny, '未知')}</span>
                <span>预留待结算：¥ {textValue(data.reserved_cny, '未知')}</span>
                <span>重复次数：{textValue(data.manifest.repeat_count)}</span>
              </div>
              <p className="tiny muted">
                预算估计与实际调用记录分开保存。恢复仍受原预算、截止时间与尝试次数限制。
              </p>
              <JsonView value={data.manifest} />
            </details>
          </>
        )
      )}
      <div className="results-toolbar">
        <h2>逐样本检查</h2>
        <label>
          失败类型
          <select
            value={failure}
            onChange={(event) => {
              setFailure(event.target.value)
              setSelected('')
            }}
          >
            <option value="all">全部样本</option>
            {Object.entries(failureLabels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="export-control">
          <select
            aria-label="导出格式"
            value={exportFormat}
            onChange={(event) => setExportFormat(event.target.value)}
          >
            <option value="jsonl">JSONL</option>
            <option value="csv">CSV</option>
            <option value="markdown">Markdown</option>
          </select>
          <button
            className="button secondary button-small"
            disabled={exportRun.isPending}
            onClick={() => exportRun.mutate()}
          >
            <Download size={15} />
            {exportRun.isPending ? '正在导出…' : '授权导出'}
          </button>
        </div>
      </div>
      <ErrorNotice error={exportRun.error} />
      <ErrorNotice
        error={results.error}
        onRetry={() => {
          void results.refetch()
        }}
      />
      {results.isPending ? (
        <Loading>正在读取逐样本结果…</Loading>
      ) : unavailable ? null : !current ? (
        <section className="card">
          <EmptyState title="尚无匹配的样本结果">
            评测处理后，结果会保存在这里。可以刷新或调整筛选。
          </EmptyState>
        </section>
      ) : (
        <div className="results-layout">
          <nav className="sample-list card" aria-label="选择样本">
            {filtered.map((item) => (
              <button
                key={item.result_id}
                className={item.result_id === current.result_id ? 'selected' : ''}
                onClick={() => setSelected(item.result_id)}
              >
                <strong>{item.sample_id}</strong>
                <span>
                  {caseLabels[item.sample.case_type] || item.case_type} · 第 {item.repeat_index + 1}{' '}
                  次
                </span>
                <StatusBadge status={item.status} />
              </button>
            ))}
          </nav>
          <div className="card inspector-card">
            <SampleInspector
              key={`${current.result_id}:${current.status}:${!!current.artifact}`}
              runId={runId}
              result={current}
              onSaved={() => {
                void results.refetch()
                void run.refetch()
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
