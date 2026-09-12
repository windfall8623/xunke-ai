import { CheckCircle2, MessageCircle, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ErrorNotice, Loading, formatDate } from '../../components/ui'
import {
  courseErrorMessage,
  courseTaskErrorMessage,
  courseTaskPending,
} from '../../services/courses'
import type {
  CourseSelfCheckCreate,
  CourseSelfCheckView,
  CourseTutorTurnView,
  LessonCheck,
} from '../../types/course'
import type { LessonTutorController } from './useLessonTutor'

export function LessonSelfCheck({
  checks,
  tutor,
  onFeedback,
  onOpenFeedback,
}: {
  checks: LessonCheck[]
  tutor: LessonTutorController
  onFeedback: (attempt: CourseSelfCheckView) => void
  onOpenFeedback: (turn: CourseTutorTurnView) => void
}) {
  const error = tutor.checksQuery.error
  return (
    <section className="card course-self-check">
      <h3>停下来，想一想</h3>
      <p className="tiny muted">
        保存自己的理解，再按需请助教反馈。这里不计分，也不改变经验值或正式练习成绩。
      </p>
      {error || tutor.inaccessible ? (
        <ErrorNotice
          error={courseErrorMessage(error || tutor.query.error || tutor.error)}
          onRetry={() => {
            void tutor.checksQuery.refetch()
          }}
        />
      ) : tutor.checksQuery.isPending ? (
        <Loading>正在恢复已保存的自检回答…</Loading>
      ) : (
        <ol className="lesson-check-list">
          {checks.map((check) => {
            const attempts = tutor.attempts
              .filter((attempt) => attempt.check_ref === check.check_ref)
              .sort(
                (a, b) =>
                  a.saved_at.localeCompare(b.saved_at) || a.attempt_id.localeCompare(b.attempt_id),
              )
            const attempt = attempts[attempts.length - 1]
            const turns = tutor.turns
              .filter((turn) => turn.check_attempt_id === attempt?.attempt_id)
              .sort(
                (a, b) =>
                  a.created_at.localeCompare(b.created_at) || a.turn_id.localeCompare(b.turn_id),
              )
            const feedback = turns[turns.length - 1] || attempt?.latest_tutor_turn
            return (
              <SelfCheckItem
                key={check.check_ref}
                check={check}
                attempt={attempt}
                feedback={feedback}
                saving={tutor.pending === `check:${check.check_ref}`}
                disabled={tutor.pending !== null}
                feedbackDisabled={tutor.busy || tutor.query.isPending || !!tutor.query.error}
                onSave={(answer) => tutor.save(check.check_ref, answer)}
                onFeedback={onFeedback}
                onOpenFeedback={onOpenFeedback}
              />
            )
          })}
        </ol>
      )}
      <ErrorNotice error={tutor.error ? courseErrorMessage(tutor.error) : null} />
    </section>
  )
}

const answerKey = (answer: CourseSelfCheckCreate['answer']) =>
  JSON.stringify(Array.isArray(answer) ? [...answer].sort() : answer.trim())

function SelfCheckItem({
  check,
  attempt,
  feedback,
  saving,
  disabled,
  feedbackDisabled,
  onSave,
  onFeedback,
  onOpenFeedback,
}: {
  check: LessonCheck
  attempt?: CourseSelfCheckView
  feedback?: CourseTutorTurnView | null
  saving: boolean
  disabled: boolean
  feedbackDisabled: boolean
  onSave: (answer: CourseSelfCheckCreate['answer']) => Promise<CourseSelfCheckView | undefined>
  onFeedback: (attempt: CourseSelfCheckView) => void
  onOpenFeedback: (turn: CourseTutorTurnView) => void
}) {
  const multiple = check.question_type === 'multiple'
  const choice = ['single', 'multiple', 'judge'].includes(check.question_type)
  const [answer, setAnswer] = useState<CourseSelfCheckCreate['answer']>(
    attempt?.answer || (multiple ? [] : ''),
  )
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (!dirty) setAnswer(attempt?.answer || (multiple ? [] : ''))
  }, [attempt?.attempt_id, dirty, multiple])
  const unchanged = !!attempt && answerKey(answer) === answerKey(attempt.answer)
  const filled = choice
    ? !!check.options?.length &&
      (Array.isArray(answer)
        ? answer.length > 0 &&
          answer.every((key) => check.options?.some((option) => option.key === key))
        : check.options.some((option) => option.key === answer))
    : typeof answer === 'string' && !!answer.trim() && answer.length <= 2000
  async function save() {
    if (!filled || disabled || unchanged) return
    const saved = await onSave(
      Array.isArray(answer) ? [...answer].sort() : choice ? answer : answer.trim(),
    )
    if (saved) {
      setAnswer(saved.answer)
      setDirty(false)
    }
  }
  return (
    <li className="lesson-check-item">
      <p className="lesson-check-prompt">{check.prompt}</p>
      {choice ? (
        check.options?.length ? (
          <fieldset disabled={disabled} className="lesson-check-options">
            <legend className="sr-only">
              {multiple ? '选择所有符合你理解的选项' : '选择符合你理解的选项'}
            </legend>
            {check.options.map((option) => {
              const selected = Array.isArray(answer)
                ? answer.includes(option.key)
                : answer === option.key
              return (
                <label
                  className={`lesson-check-option ${selected ? 'selected' : ''}`}
                  key={option.key}
                >
                  <input
                    type={multiple ? 'checkbox' : 'radio'}
                    name={`self-check-${check.check_ref}`}
                    value={option.key}
                    checked={selected}
                    onChange={() => {
                      setDirty(true)
                      setAnswer(
                        multiple
                          ? selected
                            ? (Array.isArray(answer) ? answer : []).filter(
                                (key) => key !== option.key,
                              )
                            : [...(Array.isArray(answer) ? answer : []), option.key]
                          : option.key,
                      )
                    }}
                  />
                  <span>
                    {option.key}. {option.text}
                  </span>
                </label>
              )
            })}
          </fieldset>
        ) : (
          <p className="notice">这道自检题暂缺有效选项，可以继续阅读其他内容。</p>
        )
      ) : (
        <label className="lesson-check-text">
          <span className="sr-only">填写你的理解</span>
          <textarea
            rows={4}
            maxLength={2000}
            disabled={disabled}
            value={typeof answer === 'string' ? answer : ''}
            placeholder="用自己的话写下思路、解释或疑问…"
            onChange={(event) => {
              setDirty(true)
              setAnswer(event.target.value)
            }}
          />
          <small className="tiny muted">
            {typeof answer === 'string' ? answer.length : 0} / 2000
          </small>
        </label>
      )}
      <div className="button-row">
        <button
          type="button"
          className="button secondary"
          disabled={disabled || !filled || unchanged}
          onClick={() => {
            void save()
          }}
        >
          {unchanged ? <CheckCircle2 size={16} /> : <Save size={16} />}
          {saving ? '正在保存…' : unchanged ? '回答已保存' : '保存回答'}
        </button>
        {attempt && unchanged && feedback ? (
          <button
            type="button"
            className="button secondary"
            onClick={() => onOpenFeedback(feedback)}
          >
            <MessageCircle size={16} />
            {courseTaskPending(feedback.task)
              ? '查看反馈进度'
              : feedback.task.status === 'completed'
                ? '查看教学反馈与依据'
                : '查看未完成反馈，可重试'}
          </button>
        ) : (
          <button
            type="button"
            className="button secondary"
            disabled={!attempt || !unchanged || feedbackDisabled}
            onClick={() => {
              if (attempt && unchanged) onFeedback(attempt)
            }}
          >
            <MessageCircle size={16} />
            检查我的理解
          </button>
        )}
      </div>
      <p className="tiny muted" role="status">
        {unchanged && attempt
          ? `已保存于 ${formatDate(attempt.saved_at)}`
          : attempt
            ? '修改尚未保存；保存后可检查新的理解，之前的回答仍保留。'
            : '先保存回答，再请助教给出教学反馈。'}
      </p>
      {unchanged && feedback && (
        <div className="lesson-check-feedback">
          <strong>教学反馈</strong>
          {feedback.task.status === 'completed' && feedback.answer ? (
            <p>{feedback.answer}</p>
          ) : courseTaskPending(feedback.task) ? (
            <p role="status">反馈准备中，已保存的回答不会丢失。</p>
          ) : (
            <p>{courseTaskErrorMessage(feedback.task)} 回答已经保存，可以稍后重试反馈。</p>
          )}
        </div>
      )}
    </li>
  )
}
