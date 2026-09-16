import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  FileText,
  MessageCircle,
  RotateCcw,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, formatDate } from '../../components/ui'
import {
  courseErrorMessage,
  courseKeys,
  courseReviewTime,
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
  CourseReviewStart,
  CourseReviewView,
  CourseSelfCheckView,
  CourseTutorTurnView,
  CourseWeakPoint,
} from '../../types/course'
import { CourseTaskStatus } from './CourseTaskStatus'
import { useCourseOperation } from './useCourseOperation'
import { LessonSelfCheck } from './LessonSelfCheck'
import { LessonText } from './LessonText'
import { EvidenceNoticeBar } from './EvidenceNoticeBar'
import { LessonTutorPanel, type LessonTutorContext } from './LessonTutorPanel'
import { useLessonTutor } from './useLessonTutor'

const blockLabels = { explanation: '讲解', example: '示例', reference: '资料说明', recap: '小结' }

export function CourseLesson({
  lesson,
  pendingWeakPoints,
  reviews = [],
  reviewsError,
  onReloadReviews,
  onGenerate,
  onEvidence,
  onNext,
  onUnavailable,
  generating = false,
}: {
  lesson: CourseLessonView
  pendingWeakPoints: CourseWeakPoint[]
  reviews?: CourseReviewView[]
  reviewsError?: unknown
  onReloadReviews: () => void
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
  const tutor = useLessonTutor(lesson, onUnavailable)
  const [tutorOpen, setTutorOpen] = useState(false)
  const [tutorContext, setTutorContext] = useState<LessonTutorContext>({
    mode: 'explain',
    blockIndex: null,
  })
  const [selectedTutorTurn, setSelectedTutorTurn] = useState<string>()
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
      pendingWeakPoints
        .filter((point) => point.lesson_id === lesson.lesson_id)
        .map((point) => point.link_id),
    ),
  ]
  const review = reviews
    .filter(
      (item) =>
        item.lesson_id === lesson.lesson_id &&
        item.content_version === lesson.content_version &&
        ['scheduled', 'generating', 'ready', 'failed'].includes(item.status),
    )
    .sort((a, b) => b.schedule_seq - a.schedule_seq)[0]
  const activeReviewLink = review?.active_link_id
    ? links.find((link) => link.link_id === review.active_link_id)
    : undefined
  const reviewInProgress = !!review && ['generating', 'ready'].includes(review.status)
  const reviewDue = !!review && new Date(review.due_at).getTime() <= Date.now()
  useEffect(() => {
    if (courseSourceRevoked(operation.error)) onUnavailable()
    if (operation.error instanceof ApiError && operation.error.status === 409) {
      void client.invalidateQueries({
        queryKey: courseKeys.lesson(identity, lesson.course_id, lesson.lesson_id),
      })
      void client.invalidateQueries({ queryKey: courseKeys.progress(identity, lesson.course_id) })
      void client.invalidateQueries({ queryKey: courseKeys.reviews(identity, lesson.course_id) })
    }
  }, [operation.error, onUnavailable, client, identity, lesson.course_id, lesson.lesson_id])
  function refresh() {
    void client.invalidateQueries({
      queryKey: courseKeys.lesson(identity, lesson.course_id, lesson.lesson_id),
    })
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, lesson.course_id) })
    void client.invalidateQueries({ queryKey: courseKeys.progress(identity, lesson.course_id) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
    void client.invalidateQueries({ queryKey: courseKeys.reviews(identity, lesson.course_id) })
    void client.invalidateQueries({ queryKey: courseKeys.todayAll(identity) })
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
  function startReview(early: boolean) {
    if (!review || pending || reviewsError) return
    if (activeReviewLink && !['failed', 'cancelled'].includes(activeReviewLink.task.status)) {
      openQuiz(activeReviewLink)
      return
    }
    const body: CourseReviewStart = {
      review_id: review.review_id,
      expected_revision: review.revision,
      expected_content_version: lesson.content_version,
      early,
    }
    const semantic = JSON.stringify({ body, retry_of: activeReviewLink?.task.task_id || null })
    void operation.run(
      'scheduled-review',
      async (signal) => {
        const key = await keyFor('scheduled-review', semantic)
        if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
        return coursesApi.startReview(lesson.course_id, lesson.lesson_id, body, key, signal)
      },
      (link) => {
        refresh()
        openQuiz(link)
      },
    )
  }
  async function explainBlock(mode: 'explain' | 'example', blockIndex: number) {
    setTutorContext({ mode, blockIndex })
    setSelectedTutorTurn(undefined)
    setTutorOpen(true)
    const turn = await tutor.ask({
      expected_content_version: lesson.content_version,
      mode,
      block_index: blockIndex,
      question: '',
    })
    if (turn) setSelectedTutorTurn(turn.turn_id)
  }
  async function checkUnderstanding(attempt: CourseSelfCheckView) {
    setTutorContext({ mode: 'explain', blockIndex: null })
    setSelectedTutorTurn(undefined)
    setTutorOpen(true)
    const turn = await tutor.ask({
      expected_content_version: lesson.content_version,
      mode: 'check',
      question: '',
      check_attempt_id: attempt.attempt_id,
    })
    if (turn) setSelectedTutorTurn(turn.turn_id)
  }
  function openFeedback(turn: CourseTutorTurnView) {
    setTutorContext({ mode: 'explain', blockIndex: null })
    setSelectedTutorTurn(turn.turn_id)
    setTutorOpen(true)
  }
  const canGenerate = ['not_generated', 'failed', 'cancelled'].includes(lesson.status)
  return (
    <article className="course-lesson" aria-label="当前课时">
      <header className="course-lesson-heading">
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
          <EvidenceNoticeBar warnings={lesson.warnings || []} />
          <section className="course-lesson-body" aria-label="课文">
            {lesson.blocks?.map((block, index) => (
              <section
                className={`course-block course-block-${block.type}`}
                aria-label={`${blockLabels[block.type]} ${index + 1}`}
                key={index}
              >
                <div className="section-line">
                  <h3>{blockLabels[block.type]}</h3>
                  {block.synthetic && <span className="badge">示意示例</span>}
                </div>
                <LessonText text={block.text} />
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
                <div className="course-block-help">
                  <button
                    type="button"
                    className="text-button"
                    disabled={pending || tutor.busy || tutor.query.isPending || !!tutor.query.error}
                    onClick={() => {
                      void explainBlock('explain', index)
                    }}
                  >
                    <MessageCircle size={14} />
                    解释这一段
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    disabled={pending || tutor.busy || tutor.query.isPending || !!tutor.query.error}
                    onClick={() => {
                      void explainBlock('example', index)
                    }}
                  >
                    换个例子
                  </button>
                </div>
              </section>
            ))}
          </section>
          <div className="card course-tutor-entry">
            <div>
              <strong>这里还有疑问？</strong>
              <p className="muted tiny">就本课提问、查看解释或获取提示，对话会保存在这一课。</p>
            </div>
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                setTutorContext({ mode: 'explain', blockIndex: null })
                setSelectedTutorTurn(undefined)
                setTutorOpen(true)
              }}
            >
              <MessageCircle size={17} />
              {tutor.activeTurn ? '查看助教回答进度' : '打开课内助教'}
            </button>
          </div>
          {!!lesson.checks?.length && (
            <LessonSelfCheck
              checks={lesson.checks}
              tutor={tutor}
              onFeedback={(attempt) => {
                void checkUnderstanding(attempt)
              }}
              onOpenFeedback={openFeedback}
            />
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
                    ? `待补练 ${index + 1} · 再练 3 题`
                    : '待补练 · 再练 3 题'}
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
                        {link.kind === 'initial'
                          ? '首次课后检查'
                          : link.kind === 'scheduled_review'
                            ? '课时复习'
                            : '错题补练'}
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
                        onClick={() =>
                          link.kind === 'scheduled_review'
                            ? document.getElementById('course-review')?.scrollIntoView({
                                behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)')
                                  .matches
                                  ? 'auto'
                                  : 'smooth',
                                block: 'center',
                              })
                            : createQuiz(link.kind, link.parent_link_id || undefined)
                        }
                      >
                        {link.kind === 'scheduled_review' ? '查看复习安排' : '重新生成'}
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
          <section id="course-review" className="card course-lesson-review">
            <div className="section-line">
              <h3>
                <CalendarClock size={18} />
                下次复习建议
              </h3>
              <span className="badge">全新 3 题</span>
            </div>
            {reviewsError ? (
              <ErrorNotice error={courseErrorMessage(reviewsError)} onRetry={onReloadReviews} />
            ) : review ? (
              <>
                <p className="course-review-time">
                  {courseReviewTime(review)}{' '}
                  <span className="tiny muted">（{review.timezone}）</span>
                </p>
                <p className="muted">{review.reason}</p>
                <p className="tiny muted">
                  复习不覆盖首次成绩；完成作答并确认结算后，才会安排下一次复习。
                </p>
                <div className="button-row">
                  <button
                    type="button"
                    className="button primary"
                    disabled={pending}
                    onClick={() => startReview(!reviewDue && !reviewInProgress)}
                  >
                    <RotateCcw size={16} />
                    {operation.pending === 'scheduled-review'
                      ? '正在准备…'
                      : reviewInProgress
                        ? '继续本次复习'
                        : !reviewDue
                          ? '提前复习'
                          : review.status === 'failed'
                            ? '重新准备复习 3 题'
                            : '开始复习 3 题'}
                  </button>
                  <button type="button" className="text-button" onClick={onReloadReviews}>
                    刷新安排
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="muted">完成本课练习后，会根据实际结算记录安排下一次复习。</p>
                <button type="button" className="text-button" onClick={onReloadReviews}>
                  刷新复习安排
                </button>
              </>
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
      {tutorOpen && lesson.status === 'ready' && (
        <LessonTutorPanel
          lesson={lesson}
          tutor={tutor}
          context={tutorContext}
          selectedTurnId={selectedTutorTurn}
          onClose={() => setTutorOpen(false)}
          onUnavailable={onUnavailable}
        />
      )}
    </article>
  )
}
