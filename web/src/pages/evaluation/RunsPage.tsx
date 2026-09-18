import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, Play, RefreshCw } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import {
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusBadge,
  formatDate,
} from '../../components/ui'
import { WorkbenchNav, textValue } from '../../features/evaluation/WorkbenchNav'
import { evaluationApi } from '../../services/evaluation'
import type { ApiSchemas } from '../../types/api'

const costStages = {
  retrieval: '检索',
  generation: '生成与语义验证',
  grading: '被测判分器（简答）',
  scoring: '外部质量评审（Judge）',
  indexing: '索引',
}
const priceLabels: Record<string, string> = {
  llm_input_cny_per_million: '生成输入单价',
  llm_output_cny_per_million: '生成输出单价',
  embedding_cny_per_million: '向量查询单价',
  rerank_call_cny: '重排单价',
  input_cny_per_million: '评分输入单价',
  output_cny_per_million: '评分输出单价',
}
function costAmount(value: number | null | undefined) {
  return value == null || !Number.isFinite(value)
    ? '未知'
    : value.toLocaleString('zh-CN', { maximumFractionDigits: 8 })
}

export function RunsPage() {
  const canRun = useAuth().user?.role === 'admin'
  const identity = useIdentityKey()
  const navigate = useNavigate()
  const [dataset, setDataset] = useState('')
  const [pipeline, setPipeline] = useState('')
  const [judge, setJudge] =
    useState<ApiSchemas['RunCreate']['judge_profile_id']>('deterministic-v1')
  const [repeats, setRepeats] = useState(1)
  const [budget, setBudget] = useState(10)
  const intent = useRef<{ body: string; key: string } | null>(null)
  const datasets = useQuery({
    queryKey: [identity, 'eval-datasets'],
    queryFn: ({ signal }) => evaluationApi.datasets(signal),
  })
  const pipelines = useQuery({
    queryKey: [identity, 'eval-pipelines'],
    queryFn: ({ signal }) => evaluationApi.pipelines(signal),
  })
  const judges = useQuery({
    queryKey: [identity, 'eval-judges'],
    queryFn: ({ signal }) => evaluationApi.judges(signal),
  })
  const runs = useQuery({
    queryKey: [identity, 'eval-runs'],
    queryFn: ({ signal }) => evaluationApi.runs(signal),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ['queued', 'running', 'scoring'].includes(run.status))
        ? 3500
        : false,
    refetchIntervalInBackground: false,
  })
  const selectedDataset = datasets.data?.items.find(
    (item) => `${item.dataset_id}:${item.version}` === dataset,
  )
  const selectedPipeline = pipelines.data?.items.find((item) => item.pipeline_id === pipeline)
  const selectedJudge = judges.data?.items.find((item) => item.judge_profile_id === judge)
  const estimateRequest =
    selectedDataset && selectedPipeline && selectedJudge
      ? {
          dataset_id: selectedDataset.dataset_id,
          dataset_version: selectedDataset.version,
          pipeline_id: selectedPipeline.pipeline_id,
          judge_profile_id: judge,
          repeat_count: repeats,
        }
      : null
  const estimate = useQuery({
    queryKey: [identity, 'eval-cost-estimate', estimateRequest],
    queryFn: ({ signal }) => evaluationApi.estimateRun(estimateRequest!, signal),
    enabled: !!estimateRequest,
    staleTime: 30_000,
    retry: false,
  })
  const create = useMutation({
    mutationFn: () => {
      if (!canRun) throw new Error('只有管理员可以使用系统模型创建评测运行。')
      if (
        !selectedDataset ||
        selectedDataset.status !== 'frozen' ||
        !selectedPipeline ||
        !selectedJudge
      )
        throw new Error('请选择已冻结的数据集版本、可用检索与评分方案。')
      const data = {
        dataset_id: selectedDataset.dataset_id,
        dataset_version: selectedDataset.version,
        pipeline_id: selectedPipeline.pipeline_id,
        judge_profile_id: judge,
        repeat_count: repeats,
        max_cost_cny: budget,
      }
      const body = JSON.stringify(data)
      if (intent.current?.body !== body) intent.current = { body, key: crypto.randomUUID() }
      return evaluationApi.createRun(data, intent.current.key)
    },
    onSuccess: (run) => navigate(`/evaluations/runs/${encodeURIComponent(run.run_id)}`),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (canRun && !create.isPending) create.mutate()
  }
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <PageHeading
        eyebrow="REPEATABLE EXPERIMENTS"
        title="评测运行"
        description="使用冻结数据集与白名单方案，在明确预算内运行。"
      />
      {!canRun && (
        <p className="notice">评测人员可查看本人记录、维护数据集和人工复核。创建或恢复使用系统模型的评测运行需要管理员权限。</p>
      )}
      <section className="card run-create">
        <div className="card-heading">
          <span className="icon-tile indigo">
            <Play size={20} />
          </span>
          <h2>{canRun ? '创建一次运行' : '评测方案与费用预览'}</h2>
        </div>
        <ErrorNotice error={datasets.error || pipelines.error || judges.error} />
        {datasets.isPending || pipelines.isPending || judges.isPending ? (
          <Loading>正在读取可用版本与方案…</Loading>
        ) : (
          <form onSubmit={submit}>
            <div className="run-form-grid">
              <label>
                数据集版本
                <select
                  value={dataset}
                  onChange={(event) => setDataset(event.target.value)}
                  required
                >
                  <option value="">选择冻结版本</option>
                  {datasets.data?.items
                    .filter((item) => item.status === 'frozen')
                    .map((item) => (
                      <option
                        key={`${item.dataset_id}:${item.version}`}
                        value={`${item.dataset_id}:${item.version}`}
                      >
                        {item.name} · v{item.version}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                评测方案
                <select
                  value={pipeline}
                  onChange={(event) => setPipeline(event.target.value)}
                  required
                >
                  <option value="">选择白名单方案</option>
                  {pipelines.data?.items.map((item) => (
                    <option key={item.pipeline_id} value={item.pipeline_id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                评分方案
                <select
                  value={judge}
                  onChange={(event) => setJudge(event.target.value as typeof judge)}
                  required
                >
                  {judges.data?.items.map((item) => (
                    <option key={item.judge_profile_id} value={item.judge_profile_id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                重复次数
                <select
                  value={repeats}
                  onChange={(event) => setRepeats(Number(event.target.value))}
                >
                  <option value={1}>1 次 · 诊断</option>
                  <option value={2}>2 次 · 常规评测</option>
                </select>
              </label>
              <label>
                最大预算（元）
                <input
                  type="number"
                  value={budget}
                  min={0.01}
                  max={1000}
                  step={0.01}
                  required
                  onChange={(event) => setBudget(Number(event.target.value))}
                />
              </label>
            </div>
            {selectedPipeline?.description && (
              <p className="tiny muted pipeline-description">{selectedPipeline.description}</p>
            )}
            {selectedJudge && (
              <p className="tiny muted pipeline-description">
                {selectedJudge.description}
                {judge !== 'deterministic-v1' && !selectedJudge.calibrated
                  ? ' · 尚未完成项目人工校准，结果仅供探索。'
                  : ''}
              </p>
            )}
            <div className="run-estimate">
              <div>
                <strong>预算上限 ¥ {Number.isFinite(budget) ? budget.toFixed(2) : '—'}</strong>
                <p>
                  计划样本：
                  {textValue(
                    selectedDataset?.sample_count ??
                      selectedDataset?.manifest.sample_count ??
                      (selectedDataset?.samples?.length || undefined),
                  )}{' '}
                  · 重复 {repeats} 次
                </p>
                <p role="status" aria-live="polite">
                  {!estimateRequest
                    ? '选择数据集与方案后，显示费用估算。'
                    : estimate.isPending
                      ? '正在读取单价与计算用量情景…'
                      : estimate.data?.status === 'estimated'
                        ? `首轮情景 ¥ ${costAmount(estimate.data.first_attempt_cny)} · 含重试情景 ¥ ${costAmount(estimate.data.retry_scenario_cny)}`
                        : estimate.data?.status === 'not_applicable'
                          ? '费用估算不适用：本运行没有收费模型调用。'
                          : '暂无法估算费用'}
                </p>
                <p>
                  估算按假定用量计算，实际调用与重试会造成差异；创建后分别核对已记录费用和待结算预留。预算上限不是最终账单。
                </p>
                {estimate.data && (
                  <details>
                    <summary>费用依据与用量假设</summary>
                    <p>
                      单价版本：{estimate.data.pricing_version} · 计划执行{' '}
                      {estimate.data.planned_executions} 份样本（含重复）
                    </p>
                    {estimate.data.components.map((item) => (
                      <div key={item.stage}>
                        <strong>
                          {costStages[item.stage]}：
                          {item.status === 'estimated'
                            ? `¥ ${costAmount(item.first_attempt_cny)} – ¥ ${costAmount(item.retry_scenario_cny)}（情景估算）`
                            : item.status === 'not_applicable'
                              ? '不适用'
                              : '暂无法估算'}
                        </strong>
                        {item.reason && <p>{item.reason}</p>}
                        {!!item.missing_prices?.length && (
                          <p>
                            待配置：
                            {(item.missing_prices ?? [])
                              .map((key) => priceLabels[key] ?? key)
                              .join('、')}
                          </p>
                        )}
                        {Object.entries(item.prices ?? {}).map(([key, price]) => (
                          <p key={key}>
                            {priceLabels[key] ?? key}：¥ {costAmount(price)} /{' '}
                            {key.endsWith('per_million') ? '百万 token' : '次'}
                          </p>
                        ))}
                        {item.status === 'estimated' && (
                          <p>
                            首轮 {item.first_attempt_calls} 次调用 · 含重试{' '}
                            {item.retry_scenario_calls} 次调用
                          </p>
                        )}
                        {(item.assumptions ?? []).map((assumption) => (
                          <p key={assumption}>{assumption}</p>
                        ))}
                      </div>
                    ))}
                    {estimate.data.assumptions.map((assumption) => (
                      <p key={assumption}>{assumption}</p>
                    ))}
                  </details>
                )}
                <ErrorNotice error={estimate.error} />
              </div>
              <button
                className="button primary"
                disabled={
                  !canRun || !selectedDataset || !selectedPipeline || !selectedJudge || create.isPending
                }
              >
                {create.isPending ? '正在创建…' : '创建运行'}
                <ArrowRight size={17} />
              </button>
            </div>
            <ErrorNotice error={create.error} />
          </form>
        )}
      </section>
      <div className="results-toolbar">
        <h2>运行记录</h2>
        <button
          className="button secondary button-small"
          onClick={() => {
            void runs.refetch()
          }}
          disabled={runs.isFetching}
        >
          <RefreshCw size={15} />
          刷新
        </button>
      </div>
      <ErrorNotice
        error={runs.error}
        onRetry={() => {
          void runs.refetch()
        }}
      />
      {runs.isPending ? (
        <Loading />
      ) : !runs.data?.items.length ? (
        <section className="card">
          <EmptyState title="还没有运行记录">创建第一次运行，逐个检查结果与实际用量。</EmptyState>
        </section>
      ) : (
        <div className="card table-card">
          <div className="table-scroll" tabIndex={0} role="region" aria-label="评测运行记录">
            <table>
              <thead>
                <tr>
                  <th>运行</th>
                  <th>数据集 / 方案</th>
                  <th>处理进度</th>
                  <th>状态</th>
                  <th>调用费用</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <strong>{run.run_id}</strong>
                      <small>{formatDate(run.created_at)}</small>
                    </td>
                    <td>
                      {textValue(run.dataset_id ?? run.manifest.dataset_id)} · v
                      {textValue(run.dataset_version ?? run.manifest.dataset_version)}
                      <small>{textValue(run.pipeline_id ?? run.manifest.pipeline_id)}</small>
                    </td>
                    <td>
                      {run.progress.completed} / {run.progress.total}
                      <small>
                        执行失败 {run.progress.prediction_failed ?? '—'} · 评分错误{' '}
                        {run.progress.failed}
                      </small>
                    </td>
                    <td>
                      <StatusBadge status={run.status} />
                      {!run.comparison_eligible && <small>尚不具备正式比较条件</small>}
                    </td>
                    <td>
                      <span>已记录 ¥ {costAmount(run.spent_cny)}</span>
                      <small>预留待结算 ¥ {costAmount(run.reserved_cny)}</small>
                    </td>
                    <td>
                      <Link
                        className="text-link"
                        to={`/evaluations/runs/${encodeURIComponent(run.run_id)}`}
                      >
                        检查结果
                        <ArrowRight size={14} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
