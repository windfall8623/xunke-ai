import { useState, type FormEvent } from 'react'
import { ErrorNotice } from '../../components/ui'
import type { StudyGoal, StudyGoalCreate } from '../../types/study'

export const studyPlanLabels: Record<StudyGoal['status'], string> = {
  planned: '计划中',
  active: '学习中',
  completed: '已完成',
  paused: '已暂停',
}

type Props = {
  scopeRevision: number
  goal?: StudyGoal
  disabled?: boolean
  error?: unknown
  onSubmit: (value: StudyGoalCreate) => void
  onCancel?: () => void
}

export function GoalEditor(props: Props) {
  return (
    <GoalFields
      key={`${props.goal?.goal_id || 'new'}:${props.goal?.revision || 0}:${props.scopeRevision}`}
      {...props}
    />
  )
}

function GoalFields({ scopeRevision, goal, disabled = false, error, onSubmit, onCancel }: Props) {
  const revoked = goal?.source_status === 'revoked'
  const [title, setTitle] = useState(revoked ? '' : goal?.title || '')
  const [deadline, setDeadline] = useState(goal?.deadline || '')
  const [minutes, setMinutes] = useState(String(goal?.daily_minutes || 30))
  const [status, setStatus] = useState<StudyGoal['status']>(goal?.status || 'planned')
  const valid =
    !!title.trim() &&
    title.trim().length <= 80 &&
    Number.isInteger(Number(minutes)) &&
    Number(minutes) >= 5 &&
    Number(minutes) <= 240
  function submit(event: FormEvent) {
    event.preventDefault()
    if (disabled || revoked || !valid) return
    onSubmit({
      title: title.trim(),
      scope_revision: scopeRevision,
      deadline: deadline || null,
      daily_minutes: Number(minutes),
      status,
    })
  }
  if (revoked) return <p className="notice">资料已不可用，学习目标已隐藏，暂时无法编辑。</p>
  return (
    <form
      className="stack-form"
      aria-label="学习目标编辑"
      onSubmit={submit}
      style={{ minWidth: 0 }}
    >
      <fieldset className="stack-form" disabled={disabled}>
        <label>
          学习目标
          <input
            value={title}
            maxLength={80}
            required
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <p className="muted tiny">目标使用固定范围版本 {scopeRevision}。</p>
        <div className="rubric-fields">
          <label>
            每日学习分钟
            <input
              type="number"
              min={5}
              max={240}
              step={1}
              value={minutes}
              onChange={(event) => setMinutes(event.target.value)}
            />
          </label>
          <label>
            计划完成日期
            <input
              type="date"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
            />
          </label>
          <label>
            目标状态
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value as StudyGoal['status'])}
            >
              {Object.entries(studyPlanLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <ErrorNotice error={error} />
        <div className="button-row">
          <button type="submit" className="button primary" disabled={disabled || !valid}>
            保存目标
          </button>
          {onCancel && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={onCancel}
            >
              取消编辑
            </button>
          )}
        </div>
      </fieldset>
    </form>
  )
}
