import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, Database, FileUp, Plus, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { EmptyState, ErrorNotice, Loading, PageHeading, StatusBadge } from '../../components/ui'
import { caseLabels, parseSamples } from '../../features/evaluation/dataset'
import { SampleTypeHelp } from '../../features/evaluation/SampleTypeHelp'
import { WorkbenchNav, objectValue, textValue } from '../../features/evaluation/WorkbenchNav'
import { evaluationApi } from '../../services/evaluation'

export function DatasetsPage() {
  const identity = useIdentityKey()
  const navigate = useNavigate()
  const [importing, setImporting] = useState(false)
  const [name, setName] = useState('')
  const [manifest, setManifest] = useState('{\n  "state": "draft",\n  "sources": []\n}')
  const [samples, setSamples] = useState('')
  const [validation, setValidation] = useState('')
  const query = useQuery({
    queryKey: [identity, 'eval-datasets'],
    queryFn: ({ signal }) => evaluationApi.datasets(signal),
  })
  const create = useMutation({
    mutationFn: () => {
      const data = JSON.parse(manifest)
      if (!data || typeof data !== 'object' || Array.isArray(data))
        throw new Error('Manifest 必须是一个 JSON 对象。')
      return evaluationApi.createDataset({
        name: name.trim(),
        manifest: data,
        samples: parseSamples(samples),
      })
    },
    onSuccess: (data) =>
      navigate(
        `/evaluations/datasets/${encodeURIComponent(data.dataset_id)}/versions/${data.version}`,
      ),
  })
  async function readFile(file: File | undefined, target: 'manifest' | 'samples') {
    setValidation('')
    if (!file) return
    if (file.size > 10 * 1024 * 1024) {
      setValidation('导入文件不能超过 10 MB。')
      return
    }
    try {
      const content = await file.text()
      if (target === 'manifest') setManifest(content)
      else setSamples((current) => (current.trim() ? `${current.trim()}\n${content}` : content))
    } catch {
      setValidation('无法读取该文件，请重试。')
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!create.isPending) create.mutate()
  }
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <PageHeading
        eyebrow="EVALUATION WORKSPACE"
        title="评测数据集"
        description="固定资料、题目与参考结果，检查功能、质量和费用。"
        action={
          <button
            className="button primary"
            onClick={() => {
              create.reset()
              setImporting(true)
            }}
          >
            <Plus size={17} />
            导入数据集
          </button>
        }
      />
      <div className="notice evaluation-note">
        <ShieldCheck size={20} />
        <div>只有经过授权和人工复核的数据才能冻结。生产学习资料不会自动加入评测。</div>
      </div>
      <ErrorNotice
        error={query.error}
        onRetry={() => {
          void query.refetch()
        }}
      />
      {query.isPending ? (
        <Loading />
      ) : !query.data?.items.length ? (
        <section className="card">
          <EmptyState title="建立你的第一个评测集">
            导入 Manifest 与 JSONL 样本，再完成原文标注和复核。
          </EmptyState>
        </section>
      ) : (
        <div className="dataset-grid">
          {query.data.items.map((data) => {
            const splits = data.split_counts || objectValue(data.manifest.split_counts)
            const sampleCount =
              data.sample_count ?? data.manifest.sample_count ?? (data.samples?.length || undefined)
            const counts = (split: string) =>
              typeof splits[split] === 'number'
                ? textValue(splits[split])
                : data.samples?.length
                  ? data.samples.filter((sample) => sample.split === split).length
                  : textValue(splits[split])
            return (
              <article key={`${data.dataset_id}-${data.version}`} className="card dataset-card">
                <div className="section-line">
                  <span className="icon-tile indigo">
                    <Database size={21} />
                  </span>
                  <StatusBadge status={data.status} />
                </div>
                <h2>{data.name}</h2>
                <div className="dataset-version">
                  版本 {data.version}
                  <span>·</span>
                  {textValue(sampleCount)} 个样本
                </div>
                <p className="tiny muted">
                  授权：
                  {textValue(
                    data.manifest.authorization || data.manifest.license,
                    '详见来源 Manifest',
                  )}
                </p>
                {!!data.samples?.length && (
                  <p className="tiny muted">
                    {Array.from(new Set(data.samples.map((sample) => sample.case_type)))
                      .map((kind) => caseLabels[kind] || kind)
                      .join(' · ')}
                  </p>
                )}
                <div className="split-counts">
                  <span>
                    开发<strong>{counts('dev')}</strong>
                  </span>
                  <span>
                    Judge 校准<strong>{counts('judge_calibration')}</strong>
                  </span>
                  <span>
                    锁定测试<strong>{counts('locked_test')}</strong>
                  </span>
                </div>
                <p className="checksum-line">
                  Checksum <code>{data.checksum || '冻结后生成'}</code>
                </p>
                <Link
                  className="text-link"
                  to={`/evaluations/datasets/${encodeURIComponent(data.dataset_id)}/versions/${data.version}`}
                >
                  {data.status === 'frozen' ? '查看冻结版本' : '编辑与标注'}
                  <ArrowRight size={15} />
                </Link>
              </article>
            )
          })}
        </div>
      )}
      {importing && (
        <Dialog title="导入评测数据集" className="wide-dialog" onClose={() => setImporting(false)}>
          <form className="stack-form" onSubmit={submit}>
            <label>
              数据集名称
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={120}
                required
                placeholder="例如：中文教材检索 pilot"
              />
            </label>
            <div className="import-file-row">
              <label className="button secondary button-small">
                <FileUp size={15} />
                导入 Manifest
                <input
                  className="sr-only"
                  aria-label="Manifest 文件"
                  type="file"
                  accept=".json"
                  onChange={(event) => {
                    void readFile(event.target.files?.[0], 'manifest')
                    event.target.value = ''
                  }}
                />
              </label>
              <label className="button secondary button-small">
                <FileUp size={15} />
                导入样本 JSONL
                <input
                  className="sr-only"
                  aria-label="样本文件"
                  type="file"
                  accept=".jsonl,.json"
                  onChange={(event) => {
                    void readFile(event.target.files?.[0], 'samples')
                    event.target.value = ''
                  }}
                />
              </label>
            </div>
            <label>
              Manifest JSON
              <textarea
                className="code-input"
                value={manifest}
                onChange={(event) => setManifest(event.target.value)}
                rows={6}
                required
                spellCheck={false}
              />
            </label>
            <label>
              样本 JSON / JSONL
              <textarea
                className="code-input"
                value={samples}
                onChange={(event) => setSamples(event.target.value)}
                rows={8}
                required
                spellCheck={false}
                placeholder="每行一个样本，保留稳定的 sample_id、来源引用与 split。"
              />
            </label>
            <p className="tiny muted">
              导入后先建立草稿。来源许可、hash、人工复核与 split 完整性会在冻结前验证。
            </p>
            <SampleTypeHelp />
            <ErrorNotice error={validation || create.error} />
            <button
              className="button primary"
              disabled={create.isPending || !name.trim() || !samples.trim()}
            >
              {create.isPending ? '正在导入…' : '导入为草稿'}
              <ArrowRight size={17} />
            </button>
          </form>
        </Dialog>
      )}
    </div>
  )
}
