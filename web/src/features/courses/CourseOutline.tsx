import { CheckCircle2, Clock3, FileText, PanelLeftClose, Pencil } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import type { CourseLessonSummary, CourseOutlineUpdate, CourseView } from '../../types/course'

const labels: Record<CourseLessonSummary['status'], string> = {
  not_generated: '待学习',
  generating: '内容准备中',
  ready: '可阅读',
  material_gap: '资料缺口',
  failed: '生成未完成',
  cancelled: '已取消',
  source_revoked: '资料已失效',
}

export function CourseOutline({
  course,
  selectedLessonId,
  onSelect,
  onEvidence,
  onSave,
  disabled = false,
  onCollapse,
}: {
  course: CourseView
  selectedLessonId?: string | null
  onSelect: (lesson: CourseLessonSummary) => void
  onEvidence: (sourceRef: string) => void
  onSave: (update: CourseOutlineUpdate) => Promise<boolean>
  disabled?: boolean
  onCollapse?: () => void
}) {
  const lessons = course.lessons || []
  const [editing, setEditing] = useState(false)
  const [revision, setRevision] = useState(course.revision)
  const [title, setTitle] = useState(course.title)
  const [titles, setTitles] = useState<Record<string, string>>({})
  function edit() {
    setRevision(course.revision)
    setTitle(course.title)
    setTitles(Object.fromEntries(lessons.map((lesson) => [lesson.lesson_id, lesson.title])))
    setEditing(true)
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (
      disabled ||
      revision !== course.revision ||
      !title.trim() ||
      lessons.some((lesson) => !titles[lesson.lesson_id]?.trim())
    )
      return
    const saved = await onSave({
      expected_revision: revision,
      title: title.trim(),
      lesson_titles: lessons.map((lesson) => ({
        lesson_id: lesson.lesson_id,
        title: titles[lesson.lesson_id].trim(),
      })),
    })
    if (saved) setEditing(false)
  }
  return (
    <section className="card course-outline" aria-label="课程纲要">
      <div className="section-line">
        <h2>课程目录</h2>
        <span className="muted tiny">{lessons.length} 节</span>
        {onCollapse && (
          <button
            type="button"
            className="text-button"
            onClick={onCollapse}
            aria-label="收起课程目录"
            title="收起目录，专注阅读"
          >
            <PanelLeftClose size={15} />
            收起
          </button>
        )}
      </div>
      {course.outline_editable && !editing && (
        <button type="button" className="text-button" onClick={edit} disabled={disabled}>
          <Pencil size={14} />
          调整课程与课时标题
        </button>
      )}
      {editing && course.outline_editable ? (
        <form
          className="stack-form course-outline-editor"
          onSubmit={(event) => {
            void save(event)
          }}
        >
          <label>
            课程名称
            <input
              value={title}
              maxLength={200}
              required
              disabled={disabled}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          {lessons.map((lesson, index) => (
            <label key={lesson.lesson_id}>
              第 {index + 1} 课标题
              <input
                value={titles[lesson.lesson_id] || ''}
                maxLength={200}
                required
                disabled={disabled}
                onChange={(event) =>
                  setTitles((current) => ({ ...current, [lesson.lesson_id]: event.target.value }))
                }
              />
            </label>
          ))}
          {revision !== course.revision && (
            <p className="notice">纲要已更新，请取消编辑后重新核对最新内容。</p>
          )}
          <div className="button-row">
            <button
              className="button primary"
              disabled={disabled || revision !== course.revision}
              type="submit"
            >
              {disabled ? '正在保存…' : '保存标题'}
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={disabled}
              onClick={() => setEditing(false)}
            >
              取消编辑
            </button>
          </div>
        </form>
      ) : (
        <ol className="course-outline-list">
          {lessons.map((lesson, index) => {
            const gap = lesson.availability === 'material_gap' || lesson.status === 'material_gap'
            return (
              <li
                className={`${selectedLessonId === lesson.lesson_id ? 'is-current' : ''} ${gap ? 'has-gap' : ''}`}
                key={lesson.lesson_id}
              >
                <button
                  type="button"
                  className="course-lesson-select"
                  disabled={disabled || gap || lesson.status === 'source_revoked'}
                  aria-current={selectedLessonId === lesson.lesson_id ? 'step' : undefined}
                  onClick={() => onSelect(lesson)}
                >
                  <span className="course-lesson-number">
                    {lesson.read_at ? (
                      <CheckCircle2 size={18} />
                    ) : (
                      String(index + 1).padStart(2, '0')
                    )}
                  </span>
                  <span>
                    <strong>{lesson.title}</strong>
                    <small>
                      {lesson.read_at ? '已读' : gap ? '资料缺口' : labels[lesson.status]}
                      {lesson.estimated_minutes ? ` · ${lesson.estimated_minutes} 分钟` : ''}
                    </small>
                  </span>
                </button>
                <div className="course-outline-description">
                  <p>
                    {lesson.objective ||
                      (gap
                        ? '当前资料未充分覆盖本课目标。补充资料后，可重新创建课程。'
                        : '本课目标待补充。')}
                  </p>
                  {gap && (
                    <p className="course-gap-note">本课暂不可开始。请补充相应资料后创建新课程。</p>
                  )}
                  {lesson.completion_check && (
                    <p className="tiny muted">完成检查：{lesson.completion_check}</p>
                  )}
                  {!!lesson.source_refs?.length && (
                    <div className="course-citations">
                      {lesson.source_refs?.map((ref, n) => (
                        <button
                          className="text-button"
                          type="button"
                          key={ref}
                          onClick={() => onEvidence(ref)}
                          aria-label={`查看${lesson.title}的依据 ${n + 1}`}
                        >
                          <FileText size={13} />
                          依据 {n + 1}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
      <p className="tiny muted course-outline-note">
        <Clock3 size={14} />
        {course.outline_editable
          ? '首节课开始生成前，可调整标题。'
          : '纲要已固定，随时可以切换课时学习。'}
      </p>
    </section>
  )
}
