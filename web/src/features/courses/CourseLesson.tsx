import { useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, FileText, RotateCcw } from 'lucide-react'
import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, formatDate } from '../../components/ui'
import {
  courseErrorMessage,
  courseKeys,
  coursesApi,
  courseSourceRevoked,
  courseTaskErrorMessage,
  courseTaskPending,
  createCourseSubmissionKeys,
} from '../../services/courses'
import { coursePath, withCourseReturn } from '../../services/courseNavigation'
import { ApiError } from '../../services/http'
import type {
  CourseLessonView,
  CourseQuizCreate,
  CourseQuizLinkView,
  CourseWeakPoint,
} from '../../types/course'
import { CourseTaskStatus } from './CourseTaskStatus'
import { useCourseOperation } from './useCourseOperation'

const blockLabels = { explanation: '讲解', example: '示例', reference: '资料说明', recap: '小结' }

export function CourseLesson({
  lesson,
  weakPoints,
  onGenerate,
  onEvidence,
  onNext,
  onUnavailable,
  generating = false,
}: {
  lesson: CourseLessonView
  weakPoints: CourseWeakPoint[]
  onGenerate: () => void
  onEvidence: (sourceRef: string) => void
  onNext?: () => void
  onUnavailable: () => void
  generating?: boolean
}) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const navigate = useNavigate()
  const operation = useCourseOperation()
  const keyFor = useMemo(
    () => createCourseSubmissionKeys(identity, `lesson:${lesson.course_id}:${lesson.lesson_id}`),
    [identity, lesson.course_id, lesson.lesson_id],
  )
  const returnTo = coursePath(lesson.course_id, lesson.lesson_id)
  const task = lesson.active_task || lesson.latest_task
  const pending = operation.pending !== null || generating
  const links = (lesson.quiz_links || [])
    .filter((link) => link.content_version === lesson.content_version)
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.link_id.localeCompare(b.link_id))
  const initial = [...links]
    .reverse()
    .find((link) => link.kind === 'initial' && !['failed', 'cancelled'].includes(link.task.status))
  const reviewParents = [
    ...new Set(
      weakPoints
        .filter((point) => point.lesson_id === lesson.lesson_id)
        .map((point) => point.link_id),
    ),
  ]
  useEffect(() => {
    if (courseSourceRevoked(operation.error)) onUnavailable()
    if (operation.error instanceof ApiError && operation.error.status === 409) {
      void client.invalidateQueries({
        queryKey: courseKeys.lesson(identity, lesson.course_id, lesson.lesson_id),
      })
      void client.invalidateQueries({ queryKey: courseKeys.progress(identity, lesson.course_id) })
    }
  }, [operation.error, onUnavailable, client, identity, lesson.course_id, lesson.lesson_id])
  function refresh() {
    void client.invalidateQueries({
      queryKey: courseKeys.lesson(identity, lesson.course_id, lesson.lesson_id),
    })
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, lesson.course_id) })
    void client.invalidateQueries({ queryKey: courseKeys.progress(identity, lesson.course_id) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
  }
  function openQuiz(link: CourseQuizLinkView) {
    const quizId = link.task.quiz_id || link.task.result?.quiz_id
    navigate(
      withCourseReturn(
        quizId && link.task.status === 'completed'
          ? `/quizzes/${encodeURIComponent(quizId)}`
          : `/tasks/${encodeURIComponent(link.task.task_id)}`,
        returnTo,
      ),
    )
  }
  function markRead() {
    void operation.run(
      'read',
      (signal) =>
        coursesApi.markRead(
          lesson.course_id,
          lesson.lesson_id,
          lesson.revision,
          !lesson.read_at,
          signal,
        ),
      (result) => {
        client.setQueryData(courseKeys.lesson(identity, lesson.course_id, lesson.lesson_id), result)
        refresh()
      },
    )
  }
  function createQuiz(kind: 'initial' | 'review', parentLinkId?: string) {
    const previous = [...links]
      .reverse()
      .find((link) => link.kind === kind && (link.parent_link_id || undefined) === parentLinkId)
    if (previous && !['failed', 'cancelled'].includes(previous.task.status)) {
      openQuiz(previous)
      return
    }
    const body: CourseQuizCreate = {
      expected_content_version: lesson.content_version,
      kind,
      ...(parentLinkId ? { parent_link_id: parentLinkId } : {}),
    }
    const semantic = JSON.stringify({ body, retry_of: previous?.task.task_id || null })
    void operation.run(
      'quiz',
      async (signal) => {
        const key = await keyFor('quiz', semantic)
        if (signal.aborted) throw new DOMException('已离开页面', 'AbortError')
        return coursesApi.createQuiz(lesson.course_id, lesson.lesson_id, body, key, signal)
      },
      (link) => {
        refresh()
        openQuiz(link)
      },
    )
  }
  const canGenerate = ['not_generated', 'failed', 'cancelled'].includes(lesson.status)
  return (
    <article className="course-lesson" aria-label="当前课时">
      <header className="card course-lesson-heading">
        <div className="section-line">
          <span className="eyebrow">这一课</span>
          {lesson.read_at && (
            <span className="badge">
              <CheckCircle2 size={13} />
              已读
            </span>
          )}
        </div>
        <h2>{lesson.title}</h2>
        {lesson.objective && <p className="course-objective">学习目标：{lesson.objective}</p>}
        {lesson.estimated_minutes && (
          <span className="tiny muted">预计 {lesson.estimated_minutes} 分钟</span>
        )}
      </header>
      {task && lesson.status !== 'ready' && (
        <CourseTaskStatus
          courseId={lesson.course_id}
          task={task}
          onRetry={canGenerate ? onGenerate : undefined}
          disabled={pending}
        />
      )}
      {lesson.status === 'material_gap' ? (
        <div className="card">
          <EmptyState title="这节课暂时缺少资料">
            补充与本课目标有关的资料后，可以创建新课程。
          </EmptyState>
        </div>
      ) : lesson.status !== 'ready' ? (
        !task || (lesson.status === 'not_generated' && !courseTaskPending(task)) ? (
          <div className="card">
            <EmptyState
              title="准备好学习这一课了吗？"
              action={
                <button
                  type="button"
                  className="button primary"
                  disabled={pending}
                  onClick={onGenerate}
                >
                  {generating ? '正在提交…' : '生成这一课'}
                  <ArrowRight size={16} />
                </button>
              }
            >
              按需准备本课内容，生成后会保存，方便随时回来阅读。
            </EmptyState>
          </div>
        ) : null
      ) : (
        <>
          {!!lesson.warnings?.length && (
            <div className="notice">
              <div>
                {lesson.warnings?.map((warning, index) => (
                  <p key={index}>{warning}</p>
                ))}
              </div>
            </div>
          )}
          <section className="card course-lesson-body">
            {lesson.blocks?.map((block, index) => (
              <section className={`course-block course-block-${block.type}`} key={index}>
                <div className="section-line">
                  <h3>{blockLabels[block.type]}</h3>
                  {block.synthetic && <span className="badge">示意示例</span>}
                </div>
                {block.type === 'example' ? (
                  <pre>{block.text}</pre>
                ) : (
                  <p style={{ whiteSpace: 'pre-wrap' }}>{block.text}</p>
                )}
                {!!block.source_refs?.length && (
                  <div className="course-citations">
                    {block.source_refs?.map((ref, n) => (
                      <button
                        type="button"
                        key={ref}
                        className="text-button"
                        onClick={() => onEvidence(ref)}
                        aria-label={`查看第 ${index + 1} 段依据 ${n + 1}`}
                      >
                        <FileText size={14} />
                        原文依据 {n + 1}
                      </button>
                    ))}
                  </div>
                )}
              </section>
            ))}
          </section>
          {!!lesson.checks?.length && (
            <section className="card course-self-check">
              <h3>停下来，想一想</h3>
              <p className="tiny muted">
                这些问题用于自检。完成下方的本课练习后，将保存正式作答与成绩。
              </p>
              <ol>
                {lesson.checks?.map((check) => (
                  <li key={check.check_ref}>
                    <p style={{ whiteSpace: 'pre-wrap' }}>{check.prompt}</p>
                    {!!check.options?.length && (
                      <ul>
                        {check.options?.map((option) => (
                          <li key={option.key}>
                            {option.key}. {option.text}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}
          <div className="card course-reading-actions">
            <div>
              <strong>{lesson.read_at ? '本课已标记为已读' : '读完这一课，留下学习足迹'}</strong>
              {lesson.next_step && <p className="muted">{lesson.next_step}</p>}
            </div>
            <div className="button-row">
              <button
                type="button"
                className={`button ${lesson.read_at ? 'secondary' : 'primary'}`}
                disabled={pending}
                onClick={markRead}
              >
                <CheckCircle2 size={17} />
                {operation.pending === 'read'
                  ? '正在保存…'
                  : lesson.read_at
                    ? '取消已读标记'
                    : '标记已读'}
              </button>
              {onNext && (
                <button
                  type="button"
                  className="button secondary"
                  disabled={pending}
                  onClick={onNext}
                >
                  下一课
                  <ArrowRight size={16} />
                </button>
              )}
            </div>
          </div>
          <section id="course-practice" className="card course-practice">
            <div className="section-line">
              <h3>本课练习</h3>
              <span className="badge">每组 3 题</span>
            </div>
            <p className="muted">用单选、多选或判断题检查本课目标，提交后可查看答案与解析。</p>
            <div className="button-row">
              <button
                type="button"
                className="button primary"
                disabled={pending}
                onClick={() => (initial ? openQuiz(initial) : createQuiz('initial'))}
              >
                {operation.pending === 'quiz'
                  ? '正在准备…'
                  : initial
                    ? courseTaskPending(initial.task)
                      ? '继续查看练习准备进度'
                      : '打开首次课后检查'
                    : '生成本课 3 题'}
                <ArrowRight size={16} />
              </button>
              {reviewParents.map((parentId, index) => (
                <button
                  type="button"
                  className="button secondary"
                  disabled={pending}
                  key={parentId}
                  onClick={() => createQuiz('review', parentId)}
                >
                  <RotateCcw size={16} />
                  {reviewParents.length > 1
                    ? `第 ${index + 1} 次检查错题再练`
                    : '本次错题再练 3 题'}
                </button>
              ))}
            </div>
            {!!links.length && (
              <div className="course-quiz-history">
                <h4>本课练习记录</h4>
                {links.map((link, index) => (
                  <div className="course-quiz-row" key={link.link_id}>
                    <div>
                      <strong>
                        {link.kind === 'initial' ? '首次课后检查' : '错题补练'}
                        {link.kind === 'review' ? ` · ${index + 1}` : ''}
                      </strong>
                      <p className="tiny muted">
                        {formatDate(link.created_at)} ·{' '}
                        {link.task.status === 'completed'
                          ? '题目已生成，进入查看作答记录'
                          : courseTaskPending(link.task)
                            ? '题目准备中'
                            : link.task.status === 'cancelled'
                              ? '生成已取消'
                              : courseTaskErrorMessage(link.task)}
                      </p>
                    </div>
                    {['failed', 'cancelled'].includes(link.task.status) ? (
                      <button
                        type="button"
                        className="text-button"
                        disabled={pending}
                        onClick={() => createQuiz(link.kind, link.parent_link_id || undefined)}
                      >
                        重新生成
                      </button>
                    ) : (
                      <button type="button" className="text-button" onClick={() => openQuiz(link)}>
                        打开
                        <ArrowRight size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
          {!!lesson.sources?.length && (
            <section className="card course-sources">
              <h3>本课来源</h3>
              {lesson.sources?.map((source) => (
                <button
                  key={source.source_ref}
                  type="button"
                  className="citation-button"
                  onClick={() => onEvidence(source.source_ref)}
                >
                  <FileText size={17} />
                  <span>
                    {source.title}
                    {source.locator ? ` · ${source.locator}` : ''}
                  </span>
                  <ArrowRight size={15} />
                </button>
              ))}
            </section>
          )}
        </>
      )}
      <ErrorNotice
        error={operation.error ? courseErrorMessage(operation.error) : null}
        onRetry={refresh}
      />
    </article>
  )
}
