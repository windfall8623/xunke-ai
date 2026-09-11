import { useMemo, useRef, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice } from '../../components/ui'
import {
  generatePractice,
  practiceErrorMessage,
  previewPracticeCost,
} from '../../services/practice'
import { createStudySubmissionKeys } from '../../services/study'
import type { PracticeSpec, PracticeCost } from '../../types/practice'
import type { StudyConcept, StudySpace } from '../../types/study'

export function GeneratePracticeDialog({
  space,
  concepts,
  scopeRevision,
  onClose,
}: {
  space: StudySpace
  concepts: StudyConcept[]
  scopeRevision: number
  onClose: () => void
}) {
  const identity = useIdentityKey()
  const navigate = useNavigate()
  const keyFor = useMemo(
    () => createStudySubmissionKeys(identity, `practice:${space.space_id}:${scopeRevision}`),
    [identity, space.space_id, scopeRevision],
  )
  const [selected, setSelected] = useState<string[]>([])
  const [objectives, setObjectives] = useState<Record<string, string>>({})
  const [types, setTypes] = useState<PracticeSpec['question_types']>(['cloze', 'numeric'])
  const [count, setCount] = useState(5)
  const [difficulty, setDifficulty] = useState<PracticeSpec['difficulty']>('mixed')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [preview, setPreview] = useState<PracticeCost | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const previewController = useRef<AbortController | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const eligible = concepts.filter((concept) => concept.source_status === 'active')
  const goals = selected.map((id) => (objectives[id] || '').trim())
  const costIdentity = JSON.stringify({ selected, goals, types, count, difficulty })
  useEffect(() => {
    setPreview(null)
    previewController.current?.abort()
    setPreviewing(false)
  }, [costIdentity])
  useEffect(() => () => previewController.current?.abort(), [])
  const valid =
    selected.length > 0 &&
    goals.every(Boolean) &&
    goals.join('；').length <= 2000 &&
    types.length > 0
  async function submit() {
    if (controller.current || !valid) return
    const current = new AbortController()
    controller.current = current
    setPending(true)
    setError(null)
    const body: PracticeSpec = {
      space_id: space.space_id,
      scope_revision: scopeRevision,
      concept_ids: selected,
      objectives: goals,
      question_types: types,
      question_count: count,
      difficulty,
    }
    const semantic = JSON.stringify(body)
    try {
      const key = await keyFor('quiz', semantic)
      if (current.signal.aborted) return
      const task = await generatePractice(body, key, current.signal)
      if (!current.signal.aborted) {
        keyFor.settle('quiz', semantic)
        navigate(`/practice/tasks/${encodeURIComponent(task.task_id)}`)
      }
    } catch (cause) {
      if (!current.signal.aborted) setError(cause)
    } finally {
      controller.current = null
      if (!current.signal.aborted) setPending(false)
    }
  }
  return (
    <Dialog title="生成综合练习" onClose={onClose} className="wide-dialog">
      <form
        className="stack-form"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <p className="muted">
          {space.title} · 固定资料范围版本 {scopeRevision}。选择 1–3 个概念，并说明这次想练习什么。
        </p>
        <fieldset className="stack-form" disabled={pending}>
          <legend>练习概念与目标</legend>
          {eligible.length === 0 && <p className="notice">请先在空间中添加学习概念。</p>}
          {eligible.map((concept) => (
            <div className="stack-form" key={concept.concept_id}>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={selected.includes(concept.concept_id)}
                  disabled={!selected.includes(concept.concept_id) && selected.length >= 3}
                  onChange={(event) => {
                    setSelected(
                      event.target.checked
                        ? [...selected, concept.concept_id]
                        : selected.filter((id) => id !== concept.concept_id),
                    )
                    if (event.target.checked && !objectives[concept.concept_id])
                      setObjectives({
                        ...objectives,
                        [concept.concept_id]: `理解并应用${concept.title}`,
                      })
                  }}
                />
                {concept.title}
              </label>
              {selected.includes(concept.concept_id) && (
                <label>
                  本次目标：{concept.title}
                  <textarea
                    rows={2}
                    required
                    maxLength={1000}
                    value={objectives[concept.concept_id] || ''}
                    onChange={(event) =>
                      setObjectives({ ...objectives, [concept.concept_id]: event.target.value })
                    }
                  />
                </label>
              )}
            </div>
          ))}
        </fieldset>
        <fieldset className="button-row" disabled={pending}>
          <legend>题型</legend>
          {(['cloze', 'numeric', 'short_answer'] as const).map((type) => (
            <label className="checkbox-label" key={type}>
              <input
                type="checkbox"
                checked={types.includes(type)}
                onChange={(event) =>
                  setTypes(
                    event.target.checked
                      ? [...types, type]
                      : types.filter((value) => value !== type),
                  )
                }
              />
              {({ cloze: '填空', numeric: '数值', short_answer: '短解释' } as const)[type]}
            </label>
          ))}
        </fieldset>
        <div className="button-row">
          <label>
            题量
            <input
              type="number"
              min={3}
              max={10}
              value={count}
              disabled={pending}
              onChange={(event) =>
                setCount(Math.max(3, Math.min(10, Number(event.target.value) || 3)))
              }
            />
          </label>
          <label>
            难度
            <select
              value={difficulty}
              disabled={pending}
              onChange={(event) => setDifficulty(event.target.value as typeof difficulty)}
            >
              <option value="mixed">综合</option>
              <option value="easy">基础</option>
              <option value="medium">进阶</option>
              <option value="hard">挑战</option>
            </select>
          </label>
        </div>
        <p className="tiny muted">
          短解释的自动评分会标明是否已经确认；待复核结果不计作已确认的学习证据。
        </p>
        <button
          type="button"
          className="button secondary"
          disabled={!valid || pending || previewing}
          onClick={async () => {
            const current = new AbortController()
            previewController.current = current
            setPreviewing(true)
            setError(null)
            try {
              const result = await previewPracticeCost(
                {
                  space_id: space.space_id,
                  scope_revision: scopeRevision,
                  concept_ids: selected,
                  objectives: goals,
                  question_types: types,
                  question_count: count,
                  difficulty,
                },
                current.signal,
              )
              if (!current.signal.aborted) setPreview(result)
            } catch (cause) {
              if (!current.signal.aborted) setError(cause)
            } finally {
              if (!current.signal.aborted) setPreviewing(false)
            }
          }}
        >
          {previewing ? '正在估算…' : '查看生成与评分费用上限'}
        </button>
        {preview && (
          <p className="notice">
            {preview.cost_status === 'estimated' && preview.cost_cny_upper != null
              ? `按当前价格保守估算，上限 ¥${Number(preview.cost_cny_upper).toFixed(4)}`
              : '部分服务尚未配置单价，暂无法给出完整费用上限'}
            。最多 {preview.generation_llm_call_upper} 次生成与核验调用、
            {preview.grading_llm_call_upper} 次评分调用。此预览不会调用模型或预扣费用。
          </p>
        )}
        {error != null && <ErrorNotice error={practiceErrorMessage(error)} />}
        <button className="button primary" type="submit" disabled={pending || !valid}>
          {pending ? '正在创建任务…' : '生成练习'}
        </button>
      </form>
    </Dialog>
  )
}
