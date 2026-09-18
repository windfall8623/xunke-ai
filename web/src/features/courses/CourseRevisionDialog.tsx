import { useState } from 'react'
import { Dialog } from '../../components/Dialog'
import {
  applyRevision,
  createRevisionPreview,
  startRevisionJobs,
  type CourseRevisionView,
} from '../../services/courseRevisions'
import type { CourseLessonSummary } from '../../types/course'

/**
 * 有限课程修订（B06）：一至三节课、先看影响、候选稿就绪后确认发布。
 * 确认前旧正文一直可读；发布是原子事务，历史版本可回看。
 */
export function CourseRevisionDialog({
  courseId,
  lessons,
  candidates,
  courseRevision,
  criteriaRevision,
  onApplied,
  onClose,
}: {
  courseId: string
  lessons: CourseLessonSummary[]
  candidates: CourseLessonSummary[]
  courseRevision: number
  criteriaRevision: number
  onApplied: () => void
  onClose: () => void
}) {
  const [selected, setSelected] = useState<string>(candidates[0]?.lesson_id ?? '')
  const [instruction, setInstruction] = useState('')
  const [revision, setRevision] = useState<CourseRevisionView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const ready = revision?.status === 'ready'

  async function run() {
    if (!selected || pending) return
    setPending(true)
    setError(null)
    try {
      const lesson = lessons.find((item) => item.lesson_id === selected)
      let view = revision
      if (!view) {
        view = await createRevisionPreview(courseId, {
          expected_course_revision: courseRevision,
          expected_criteria_revision: criteriaRevision,
          lessons: [{ lesson_id: selected, expected_content_version: lesson?.content_version ?? 0,
                      instruction: instruction.trim() || '按当前目标修订这一课' }],
        }, crypto.randomUUID())
        setRevision(view)
      }
      view = await startRevisionJobs(courseId, {
        revision_id: view.revision_id,
        expected_revision: view.revision,
      }, crypto.randomUUID())
      setRevision(view)
      // 候选稿由后台 worker 写回；这里只提示稍后查看，不做无界轮询。
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '修订请求未完成，请稍后重试')
    } finally {
      setPending(false)
    }
  }

  async function apply() {
    if (!revision || pending) return
    setPending(true)
    setError(null)
    try {
      const applied = await applyRevision(courseId, revision.revision_id, {
        expected_course_revision: revision.expected_course_revision,
        expected_revision: revision.revision,
      }, crypto.randomUUID())
      setRevision(applied)
      onApplied()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发布未完成，旧正文未受影响')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog title="修订这一课" onClose={onClose} className="course-revision-dialog">
      {!revision && (
        <form onSubmit={(event) => { event.preventDefault(); void run() }}>
          <label htmlFor="revision-lesson">选择要修订的课（一次最多三节）</label>
          <select
            id="revision-lesson"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            {candidates.map((lesson) => (
              <option value={lesson.lesson_id} key={lesson.lesson_id}>{lesson.title}</option>
            ))}
          </select>
          <label htmlFor="revision-instruction">修改方向</label>
          <textarea
            id="revision-instruction"
            value={instruction}
            rows={3}
            maxLength={1000}
            onChange={(event) => setInstruction(event.target.value)}
          />
          <p className="tiny muted">
            预览不调用模型；确认发布前旧正文一直可读，发布后可在版本历史回看。
          </p>
          <button type="submit" className="button primary" disabled={pending || !selected}>
            {pending ? '正在生成候选稿…' : '生成候选稿'}
          </button>
        </form>
      )}
      {revision && (
        <div className="course-revision-status">
          <p>修订状态：{{
            preview: '已生成影响预览',
            generating: '候选稿生成中，可稍后回到本页查看',
            ready: '候选稿已就绪，确认后发布新版本',
            failed: '候选稿生成失败，旧正文未受影响',
            cancelled: '已取消',
            applied: '已发布新版本，可在版本历史回看旧版',
          }[revision.status]}</p>
          {(revision.impacts ?? []).map((impact) => (
            <p className="tiny muted" key={String(impact.lesson_id ?? '')}>
              课时将更新到 v{String(impact.next_content_version ?? '')}；现有检查保留，证据需重新验证。
            </p>
          ))}
          {ready && (
            <button type="button" className="button primary" disabled={pending} onClick={() => void apply()}>
              {pending ? '正在发布…' : '确认发布新版本'}
            </button>
          )}
        </div>
      )}
      {error && <p role="alert" className="course-feedback-error">{error}</p>}
    </Dialog>
  )
}
