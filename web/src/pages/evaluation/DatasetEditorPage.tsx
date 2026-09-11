import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, Copy, LockKeyhole, Save, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading, PageHeading, StatusBadge } from '../../components/ui'
import { caseLabels, parseSamples, samplePrompt } from '../../features/evaluation/dataset'
import { SampleTypeHelp } from '../../features/evaluation/SampleTypeHelp'
import { SpanEditor } from '../../features/evaluation/SpanEditor'
import { JsonView, WorkbenchNav } from '../../features/evaluation/WorkbenchNav'
import { evaluationApi } from '../../services/evaluation'
import type { DatasetSample, DatasetVersion, JsonObject } from '../../types/evaluation'

const freezeChecks: Record<string, string> = {
  source_rights: '来源授权与许可已核对',
  spans: '原文范围与 hash 已核对',
  family_split: '文档家族与 split 已核对',
  answerability: '可回答性与请求题量已核对',
  second_review: '独立复核覆盖与限制已核对',
}

export function DatasetEditorPage() {
  const { datasetId = '', version = '1' } = useParams()
  const identity = useIdentityKey()
  const query = useQuery({
    queryKey: [identity, 'eval-dataset', datasetId, version],
    queryFn: ({ signal }) => evaluationApi.dataset(datasetId, Number(version), signal),
  })
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <Link className="back-link" to="/evaluations">
        <ArrowLeft size={15} />
        全部数据集
      </Link>
      {query.isPending ? (
        <Loading />
      ) : query.error || !query.data ? (
        <ErrorNotice
          error={query.error || '版本不可用'}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : (
        <DatasetEditor
          key={`${datasetId}:${version}:${query.data.revision}`}
          data={query.data}
          onSaved={() => {
            void query.refetch()
          }}
        />
      )}
    </div>
  )
}
function DatasetEditor({ data, onSaved }: { data: DatasetVersion; onSaved: () => void }) {
  const navigate = useNavigate()
  const [name, setName] = useState(data.name)
  const [manifest, setManifest] = useState(JSON.stringify(data.manifest, null, 2))
  const [samples, setSamples] = useState(JSON.stringify(data.samples || [], null, 2))
  const [sampleIndex, setSampleIndex] = useState(0)
  const [reason, setReason] = useState('')
  const [verdict, setVerdict] = useState<'approved' | 'needs_changes'>('approved')
  const [validation, setValidation] = useState('')
  const [removing, setRemoving] = useState(false)
  const [checklist, setChecklist] = useState<Record<string, boolean>>({})
  const checklistComplete = Object.keys(freezeChecks).every((key) => checklist[key] === true)
  const frozen = data.status === 'frozen' || data.status === 'revoked'
  const changed =
    name !== data.name ||
    manifest !== JSON.stringify(data.manifest, null, 2) ||
    samples !== JSON.stringify(data.samples || [], null, 2)
  let parsedSamples: DatasetSample[] = []
  try {
    parsedSamples = parseSamples(samples)
  } catch {
    /* Editable JSON can be temporarily incomplete. */
  }
  const current = parsedSamples[sampleIndex]
  const save = useMutation({
    mutationFn: () => {
      const value = JSON.parse(manifest)
      if (!value || typeof value !== 'object' || Array.isArray(value))
        throw new Error('Manifest 必须是 JSON 对象。')
      return evaluationApi.patchDataset(data.dataset_id, data.version, {
        revision: data.revision,
        name: name.trim(),
        manifest: value,
        samples: parseSamples(samples),
      })
    },
    onSuccess: onSaved,
  })
  const freeze = useMutation({
    mutationFn: () => evaluationApi.freeze(data.dataset_id, data.version, data.revision, checklist),
    onSuccess: onSaved,
  })
  const copy = useMutation({
    mutationFn: () =>
      evaluationApi.createDataset({
        dataset_id: data.dataset_id,
        name: data.name,
        manifest: { ...data.manifest, state: 'draft' },
        samples: data.samples || [],
      }),
    onSuccess: (value) =>
      navigate(
        `/evaluations/datasets/${encodeURIComponent(value.dataset_id)}/versions/${value.version}`,
      ),
  })
  const revoke = useMutation({
    mutationFn: () => evaluationApi.revoke(data.dataset_id, data.version),
    onSuccess: () => navigate('/evaluations'),
  })
  const sampleReview = useMutation({
    mutationFn: () =>
      evaluationApi.reviewSample(data.dataset_id, data.version, current.sample_id, {
        expected_revision: data.revision,
        verdict,
        comment: reason.trim(),
      }),
    onSuccess: onSaved,
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!save.isPending) save.mutate()
  }
  function updateSample(update: (sample: DatasetSample) => DatasetSample) {
    setValidation('')
    try {
      const list = parseSamples(samples)
      list[sampleIndex] = update(list[sampleIndex])
      setSamples(JSON.stringify(list, null, 2))
    } catch (cause) {
      setValidation(cause instanceof Error ? cause.message : '样本格式无效')
    }
  }
  function addSpan(span: JsonObject) {
    updateSample((sample) => ({
      ...sample,
      gold_evidence_groups: [
        ...(sample.gold_evidence_groups || []),
        { group_id: `fact-${crypto.randomUUID().slice(0, 8)}`, alternatives: [{ spans: [span] }] },
      ],
    }))
  }
  function approveSample() {
    if (!reason.trim() || changed || !current || sampleReview.isPending) return
    sampleReview.mutate()
  }
  return (
    <>
      <PageHeading
        title={data.name}
        description={`版本 ${data.version} · revision ${data.revision}`}
        action={
          <div className="button-row">
            <StatusBadge status={data.status} />
            <button
              className="button secondary button-small"
              disabled={copy.isPending || data.status === 'revoked'}
              onClick={() => copy.mutate()}
            >
              <Copy size={15} />
              创建新版本
            </button>
            <button
              className="icon-button"
              aria-label="撤销数据集版本"
              onClick={() => setRemoving(true)}
            >
              <Trash2 size={16} />
            </button>
          </div>
        }
      />
      {frozen && (
        <div className="notice evaluation-note">
          <LockKeyhole size={19} />
          {data.status === 'revoked'
            ? '此版本已撤销，不可编辑或运行。'
            : '冻结版本保持只读。修改标签或来源时，请创建新版本。'}
        </div>
      )}
      <ErrorNotice
        error={save.error || freeze.error || copy.error || sampleReview.error || validation}
      />
      {frozen ? (
        <section className="card">
          <div className="section-line">
            <h2>冻结资料与样本</h2>
            <span className="badge">{data.samples?.length ?? '—'} 个样本</span>
          </div>
          <p className="checksum-line">
            Checksum <code>{data.checksum || '—'}</code>
          </p>
          <details open className="technical-details">
            <summary>Manifest</summary>
            <JsonView value={data.manifest} />
          </details>
          <details open className="technical-details">
            <summary>样本与 Gold</summary>
            <JsonView value={data.samples} />
          </details>
        </section>
      ) : (
        <>
          <div className="dataset-editor-layout">
            <form className="card stack-form" onSubmit={submit}>
              <h2>版本内容</h2>
              <label>
                数据集名称
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={120}
                  required
                />
              </label>
              <label>
                Manifest JSON
                <textarea
                  className="code-input"
                  value={manifest}
                  onChange={(event) => setManifest(event.target.value)}
                  rows={9}
                  spellCheck={false}
                />
              </label>
              <label>
                样本与标注 JSON
                <textarea
                  className="code-input"
                  value={samples}
                  onChange={(event) => setSamples(event.target.value)}
                  rows={18}
                  spellCheck={false}
                />
              </label>
              <p className="tiny muted">
                包含 source_refs、gold_evidence_groups、ranking_labels、split 与人工
                review_records。保存带 revision，冲突后请重新读取版本。
              </p>
              <SampleTypeHelp />
              <button className="button primary" disabled={save.isPending || !name.trim()}>
                <Save size={16} />
                {save.isPending ? '正在保存…' : '保存草稿'}
              </button>
            </form>
            <aside className="card annotation-panel">
              <h2>核对原文与人工标注</h2>
              {current ? (
                <>
                  <label className="standalone-label">
                    选择样本
                    <select
                      value={sampleIndex}
                      onChange={(event) => setSampleIndex(Number(event.target.value))}
                    >
                      {parsedSamples.map((sample, index) => (
                        <option key={sample.sample_id} value={index}>
                          {sample.sample_id} · {caseLabels[sample.case_type]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="sample-query">{samplePrompt(current)}</p>
                  <SpanEditor key={current.sample_id} sample={current} onAdd={addSpan} />
                  <div className="annotation-review">
                    <h3>人工确认此样本</h3>
                    <p className="tiny muted">
                      核对 Gold
                      与来源后填写理由。服务端记录当前账号和时间，独立复核覆盖由实际审核账号计算。
                    </p>
                    <label className="standalone-label">
                      复核结论
                      <select
                        value={verdict}
                        onChange={(event) =>
                          setVerdict(event.target.value as 'approved' | 'needs_changes')
                        }
                      >
                        <option value="approved">已核对，可作为 Gold</option>
                        <option value="needs_changes">需要修改或补充依据</option>
                      </select>
                    </label>
                    <label className="standalone-label">
                      标注复核理由
                      <textarea
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        rows={3}
                      />
                    </label>
                    <button
                      className="button secondary button-small"
                      disabled={!reason.trim() || changed || sampleReview.isPending}
                      onClick={approveSample}
                    >
                      <CheckCircle2 size={15} />
                      记录人工确认
                    </button>
                    <p className="tiny muted">
                      {changed
                        ? '请先保存更改，再对已保存的样本记录复核。'
                        : '此操作直接保存实名复核记录，并更新版本 revision。'}
                    </p>
                  </div>
                </>
              ) : (
                <p className="muted tiny">请先填写格式有效、含 sample_id 的样本 JSON。</p>
              )}
            </aside>
          </div>
          <div className="card freeze-card">
            <div>
              <h2>完成复核，冻结本版本</h2>
              <p>冻结前验证来源授权、hash、Gold、split 与必要的独立复核记录。</p>
              <fieldset className="freeze-checklist">
                <legend className="sr-only">冻结前核对</legend>
                {Object.entries(freezeChecks).map(([key, label]) => (
                  <label className="checkbox-row" key={key}>
                    <input
                      type="checkbox"
                      checked={checklist[key] === true}
                      onChange={(event) =>
                        setChecklist((current) => ({ ...current, [key]: event.target.checked }))
                      }
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              <p className="tiny muted">
                单人复核可用于标有暂定状态的内部实验；勾选核对项不会补造第二位审核人，也不代表正式发布通过。
              </p>
            </div>
            <button
              className="button primary"
              disabled={changed || !checklistComplete || freeze.isPending || save.isPending}
              onClick={() => freeze.mutate()}
            >
              <LockKeyhole size={16} />
              {changed ? '请先保存更改' : freeze.isPending ? '正在验证…' : '验证并冻结'}
            </button>
          </div>
        </>
      )}
      {removing && (
        <Dialog title="撤销数据集版本" onClose={() => setRemoving(false)}>
          <p>
            确认撤销「{data.name}」版本 {data.version}？
          </p>
          <p className="tiny muted">相关运行将重新检查授权，这个版本的可读工件会被清理。</p>
          <ErrorNotice error={revoke.error} />
          <div className="button-row">
            <button className="button secondary" onClick={() => setRemoving(false)}>
              保留版本
            </button>
            <button
              className="button danger"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate()}
            >
              确认撤销
            </button>
          </div>
        </Dialog>
      )}
    </>
  )
}
