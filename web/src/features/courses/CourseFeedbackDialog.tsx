import { useEffect, useMemo, useState } from 'react'
import { Dialog } from '../../components/Dialog'
import {
  correctionEffectLabel,
  createCourseCorrection,
  createCourseFeedback,
  listCourseFeedback,
  latestCorrection,
  type CourseFeedbackTarget,
  type CourseFeedbackView,
} from '../../services/courseFeedback'

export type CourseFeedbackEntry = {
  kind: 'confusion' | 'content_error' | 'grading_review'
  target: CourseFeedbackTarget
}

const issueLabels = {
  confusion: '没理解',
  content_error: '内容有误',
  grading_review: '评分有异议',
} as const

const issueHints = {
  confusion: '记录卡住的位置；需要讲解可以直接使用段落里的「问助教」。',
  content_error: '说明哪里与资料或事实不一致；确认后会先预览修订，不会直接改动正文。',
  grading_review: '说明你认为评分有误的原因；有权限复核前，现有成绩保持不变。',
} as const

/**
 * 就地反馈入口：记录问题、维护个人纠正说明。
 * 教学解释、个人纠正与正式判分状态分开展示，模型建议不会显示成已确认。
 */
export function CourseFeedbackDialog({
  courseId,
  entry,
  onClose,
}: {
  courseId: string
  entry: CourseFeedbackEntry
  onClose: () => void
}) {
  const [views, setViews] = useState<CourseFeedbackView[] | null>(null)
  const [comment, setComment] = useState('')
  const [correction, setCorrection] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [kind, setKind] = useState(entry.kind)
  const query = useMemo(
    () => ({
      lesson_id: 'lesson_id' in entry.target ? entry.target.lesson_id : undefined,
      check_attempt_id:
        entry.target.kind === 'self_check' ? entry.target.check_attempt_id : undefined,
      course_assessment_id:
        entry.target.kind === 'course_assessment' ? entry.target.course_assessment_id : undefined,
    }),
    [entry.target],
  )

  useEffect(() => {
    let active = true
    listCourseFeedback(courseId, query)
      .then((list) => {
        if (active) setViews(list.items)
      })
      .catch(() => {
        if (active) setViews([])
      })
    return () => {
      active = false
    }
  }, [courseId, query])

  const existing = views?.find((view) => JSON.stringify(view.target) === JSON.stringify(entry.target))

  async function submit() {
    if (!comment.trim() || pending) return
    setPending(true)
    setError(null)
    try {
      const saved = await createCourseFeedback(
        courseId,
        { issue_kind: kind, target: entry.target, comment: comment.trim(), allow_evaluation_use: false },
        crypto.randomUUID(),
      )
      setViews((current) => [...(current ?? []).filter((v) => v.feedback_id !== saved.feedback_id), saved])
      setComment('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提交未完成，请稍后重试')
    } finally {
      setPending(false)
    }
  }

  async function addCorrection(feedbackId: string, expectedRevision: number) {
    if (!correction.trim() || pending) return
    setPending(true)
    setError(null)
    try {
      await createCourseCorrection(
        courseId,
        feedbackId,
        { expected_revision: expectedRevision, text: correction.trim() },
        crypto.randomUUID(),
      )
      const list = await listCourseFeedback(courseId, query)
      setViews(list.items)
      setCorrection('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提交未完成，请稍后重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog title={`${issueLabels[entry.kind]} · 反馈与纠正`} onClose={onClose} className="course-feedback-dialog">
      {existing ? (
        <div className="course-feedback-thread">
          <p className="course-feedback-comment">{existing.comment}</p>
          <p className="course-feedback-status">
            {existing.status === 'open' ? '已记录，待处理' : existing.status === 'resolved' ? '已标记解决' : '已复核退回'}
          </p>
          <div className="course-feedback-corrections">
            {(existing.corrections ?? []).map((item) => (
              <p
                key={item.correction_id}
                className={item.confirmation === 'confirmed' ? 'correction confirmed' : 'correction'}
              >
                {item.provenance === 'human_reviewer' ? '复核说明' : item.provenance === 'model_proposal' ? '助教建议（暂定）' : '我的纠正'}
                ：{item.text}
              </p>
            ))}
          </div>
          <p className="course-feedback-effect">{correctionEffectLabel(existing)}</p>
          {existing.status !== 'rejected' && (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void addCorrection(existing.feedback_id, existing.revision)
              }}
            >
              <label htmlFor="course-correction-text">补充或更正我的说明</label>
              <textarea
                id="course-correction-text"
                value={correction}
                onChange={(event) => setCorrection(event.target.value)}
                rows={3}
                maxLength={2000}
              />
              <button type="submit" className="button secondary" disabled={pending || !correction.trim()}>
                保存新说明
              </button>
            </form>
          )}
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <fieldset className="course-feedback-kind" disabled={pending}>
            <legend>问题类型</legend>
            {(Object.keys(issueLabels) as Array<keyof typeof issueLabels>).map((option) => (
              <label key={option}>
                <input
                  type="radio"
                  name="feedback-kind"
                  checked={kind === option}
                  onChange={() => setKind(option)}
                />
                {issueLabels[option]}
              </label>
            ))}
          </fieldset>
          <p className="course-feedback-hint">{issueHints[kind]}</p>
          <label htmlFor="course-feedback-comment">{issueLabels[kind]}说明</label>
          <textarea
            id="course-feedback-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            rows={4}
            maxLength={2000}
            autoFocus
          />
          <button type="submit" className="button primary" disabled={pending || !comment.trim()}>
            {pending ? '正在保存…' : '保存这条反馈'}
          </button>
        </form>
      )}
      {error && <p role="alert" className="course-feedback-error">{error}</p>}
      {views === null && <p>正在读取已有反馈…</p>}
    </Dialog>
  )
}

export const feedbackButtonLabel = (kind: CourseFeedbackEntry['kind']) =>
  issueLabels[kind]

export { latestCorrection }
