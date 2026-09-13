import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, BookOpen, PanelLeftOpen, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { CourseEvidenceDrawer } from '../../features/courses/CourseEvidenceDrawer'
import { EvidenceNoticeBar } from '../../features/courses/EvidenceNoticeBar'
import { CourseAgentProgress } from '../../features/courses/CourseAgentProgress'
import { CourseAssessmentPanel } from '../../features/courses/CourseAssessmentPanel'
import { CourseRevisionDialog } from '../../features/courses/CourseRevisionDialog'
import { CourseVersionHistory } from '../../features/courses/CourseVersionHistory'
import { CourseExportActions } from '../../features/courses/CourseExportActions'
import { CourseLesson } from '../../features/courses/CourseLesson'
import { CourseOutline } from '../../features/courses/CourseOutline'
import { CourseProgress } from '../../features/courses/CourseProgress'
import { CourseQualityNotice } from '../../features/courses/CourseQualityNotice'
import { CourseTaskStatus } from '../../features/courses/CourseTaskStatus'
import { useCourseOperation } from '../../features/courses/useCourseOperation'
import {
  courseErrorMessage,
  courseKeys,
  coursesApi,
  courseSourceRevoked,
  courseTaskPending,
  createCourseSubmissionKeys,
} from '../../services/courses'
import { coursePath, scrollCourseSection, withCourseReturn } from '../../services/courseNavigation'
import { ApiError } from '../../services/http'
import type {
  CourseLessonSummary,
  CourseLessonView,
  CourseNextAction,
  CourseOutlineUpdate,
  CourseTaskView,
  CourseView,
} from '../../types/course'
import '../../styles/courses.scss'

export function CoursePage() {
  const { courseId = '' } = useParams()
  const identity = useIdentityKey()
  return <CourseWorkspace key={`${identity}:${courseId}`} courseId={courseId} identity={identity} />
}

function CourseWorkspace({ courseId, identity }: { courseId: string; identity: string | number }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const lessonId = params.get('lesson') || ''
  const operation = useCourseOperation()
  const keyFor = useMemo(() => createCourseSubmissionKeys(identity, courseId), [identity, courseId])
  const [evidence, setEvidence] = useState<{ sourceRef: string; lessonId?: string } | null>(null)
  const focusOutlineControl = useRef(false)
  const [outlineCollapsed, setOutlineCollapsed] = useState(() => {
    try {
      const saved = localStorage.getItem('xunke.outlineCollapsed')
      if (saved !== null) return saved === '1'
    } catch { /* Optional reading preference; a blocked store must not block the lesson. */ }
    return window.innerWidth < 1200
  })
  function toggleOutline() {
    focusOutlineControl.current = true
    setOutlineCollapsed((current) => {
      try { localStorage.setItem('xunke.outlineCollapsed', current ? '0' : '1') } catch { /* Optional preference. */ }
      return !current
    })
  }
  useEffect(() => {
    if (!focusOutlineControl.current) return
    focusOutlineControl.current = false
    document.getElementById(outlineCollapsed ? 'course-outline-toggle' : 'course-outline-collapse')?.focus({ preventScroll: true })
  }, [outlineCollapsed])

  const [sourceHidden, setSourceHidden] = useState(false)
  const [revisionOpen, setRevisionOpen] = useState(false)
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false)
  const courseQuery = useQuery({
    queryKey: courseKeys.course(identity, courseId),
    queryFn: ({ signal }) => coursesApi.course(courseId, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
  })
  const course = courseQuery.data
  const lessons = course?.lessons || []
  const revoked =
    sourceHidden || course?.source_status === 'revoked' || course?.status === 'source_revoked'
  const lessonQuery = useQuery({
    queryKey: courseKeys.lesson(identity, courseId, lessonId),
    queryFn: async ({ signal }) => {
      const lesson = await coursesApi.lesson(courseId, lessonId, signal)
      if (lesson.course_id !== courseId || lesson.lesson_id !== lessonId)
        throw new ApiError('课时不属于当前课程。', 404, 'course_lesson_not_found')
      return lesson
    },
    // The server checks the URL's course/lesson ownership; a cached outline is not authorization.
    enabled: !!lessonId && !!course && !courseQuery.error && !revoked,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) =>
      state.state.data?.quiz_links?.some((link) => courseTaskPending(link.task)) ? 3000 : false,
    refetchIntervalInBackground: false,
  })
  const progressQuery = useQuery({
    queryKey: courseKeys.progress(identity, courseId),
    queryFn: ({ signal }) => coursesApi.progress(courseId, signal),
    enabled: !!lessons.length && !courseQuery.error && !revoked,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) =>
      state.state.data?.next_action.type === 'continue_quiz' &&
      state.state.data.next_action.task_id &&
      !state.state.data.next_action.quiz_id
        ? 3500
        : false,
    refetchIntervalInBackground: false,
  })
  const reviewsQuery = useQuery({
    queryKey: courseKeys.reviews(identity, courseId),
    queryFn: ({ signal }) => coursesApi.reviews(courseId, signal),
    enabled: !!lessons.length && !courseQuery.error && !revoked,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) =>
      state.state.data?.some((review) => review.status === 'generating')
        ? 3000
        : progressQuery.data?.practiced_lessons &&
            !state.state.data?.some((review) =>
              ['scheduled', 'generating', 'ready', 'failed'].includes(review.status),
            )
          ? 5000
          : false,
    refetchIntervalInBackground: false,
  })
  const hideSource = useCallback(() => {
    setSourceHidden(true)
    setEvidence(null)
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
    void client.invalidateQueries({ queryKey: courseKeys.todayAll(identity) })
  }, [client, identity, courseId])
  useEffect(() => {
    if (
      !sourceHidden &&
      [
        courseQuery.error,
        lessonQuery.error,
        progressQuery.error,
        reviewsQuery.error,
        operation.error,
      ].some(courseSourceRevoked)
    )
      hideSource()
    if (operation.error instanceof ApiError && operation.error.status === 409) {
      void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
      if (lessonId)
        void client.invalidateQueries({ queryKey: courseKeys.lesson(identity, courseId, lessonId) })
    }
  }, [
    courseQuery.error,
    lessonQuery.error,
    progressQuery.error,
    reviewsQuery.error,
    operation.error,
    sourceHidden,
    hideSource,
    client,
    identity,
    courseId,
    lessonId,
  ])
  useEffect(() => {
    if (!lessonId && course?.resume_lesson_id && !revoked && !courseQuery.error)
      setParams({ lesson: course.resume_lesson_id }, { replace: true })
  }, [lessonId, course?.resume_lesson_id, revoked, courseQuery.error, setParams])
  useEffect(() => {
    if (
      ['#course-practice', '#course-review', '#lesson-summary'].includes(location.hash) &&
      lessonQuery.data?.status === 'ready'
    )
      scrollCourseSection(location.hash.slice(1), 'start', true)
  }, [location.hash, lessonQuery.data?.lesson_id, lessonQuery.data?.status])
  function invalidate(affectedLesson?: string) {
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.progress(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
    void client.invalidateQueries({ queryKey: courseKeys.reviews(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.todayAll(identity) })
    if (affectedLesson)
      void client.invalidateQueries({
        queryKey: courseKeys.lesson(identity, courseId, affectedLesson),
      })
  }
  function rememberTask(task: CourseTaskView) {
    client.setQueryData(courseKeys.task(identity, courseId, task.task_id, task.lesson_id), task)
    if (task.kind === 'course_outline') {
      client.setQueryData<CourseView>(courseKeys.course(identity, courseId), (current) =>
        current
          ? {
              ...current,
              active_task: task,
              latest_task: task,
              status: courseTaskPending(task) ? 'generating' : current.status,
            }
          : current,
      )
    } else if (task.lesson_id) {
      client.setQueryData<CourseLessonView>(
        courseKeys.lesson(identity, courseId, task.lesson_id),
        (current) =>
          current
            ? {
                ...current,
                active_task: courseTaskPending(task) ? task : null,
                latest_task: task,
                status: courseTaskPending(task) ? 'generating' : current.status,
              }
            : current,
      )
      client.setQueryData<CourseView>(courseKeys.course(identity, courseId), (current) =>
        current ? { ...current, outline_editable: false } : current,
      )
    }
    invalidate(task.lesson_id || undefined)
  }
  function generateLesson(id: string, requestQualityReview = false) {
    if (!course || revoked) return
    const summary = lessons.find((lesson) => lesson.lesson_id === id)
    if (
      !summary ||
      summary.availability === 'material_gap' ||
      summary.status === 'source_revoked' ||
      summary.status === 'ready'
    )
      return
    const previous = lessonQuery.data?.lesson_id === id ? lessonQuery.data.latest_task : null
    const semantic = JSON.stringify({
      lesson_id: id,
      expected_course_revision: course.revision,
      // 显式核对请求属于这次任务的一部分，必须进入幂等指纹。
      request_quality_review: requestQualityReview,
      retry_of:
        previous && ['failed', 'cancelled'].includes(previous.status) ? previous.task_id : null,
    })
    void operation.run(
      `lesson:${id}`,
      async (signal) => {
        const key = await keyFor('lesson', semantic)
        if (signal.aborted) throw new DOMException('已离开页面', 'AbortError')
        return coursesApi.generateLesson(
          courseId,
          id,
          course.revision,
          key,
          signal,
          requestQualityReview,
        )
      },
      rememberTask,
    )
  }
  function selectLesson(lesson: CourseLessonSummary) {
    setEvidence(null)
    setParams({ lesson: lesson.lesson_id })
    if (lesson.status === 'not_generated' && lesson.availability !== 'material_gap')
      generateLesson(lesson.lesson_id)
  }
  function retryOutline() {
    if (!course || revoked || !['failed', 'cancelled'].includes(course.status)) return
    const semantic = JSON.stringify({
      course_id: courseId,
      revision: course.revision,
      retry_of: course.latest_task?.task_id || null,
    })
    void operation.run(
      'outline',
      async (signal) => {
        const key = await keyFor('outline', semantic)
        if (signal.aborted) throw new DOMException('已离开页面', 'AbortError')
        return coursesApi.retryOutline(courseId, key, signal)
      },
      rememberTask,
    )
  }
  async function saveOutline(update: CourseOutlineUpdate) {
    const saved = await operation.run(
      'save-outline',
      (signal) => coursesApi.updateOutline(courseId, update, signal),
      (result) => {
        client.setQueryData(courseKeys.course(identity, courseId), result)
        void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
      },
    )
    return !!saved
  }
  function nextAction(action: CourseNextAction) {
    const returnTo = coursePath(courseId, action.lesson_id)
    if (action.type === 'continue_quiz') {
      if (action.quiz_id) {
        navigate(withCourseReturn(`/quizzes/${encodeURIComponent(action.quiz_id)}`, returnTo))
        return
      }
      if (action.task_id) {
        navigate(withCourseReturn(`/tasks/${encodeURIComponent(action.task_id)}`, returnTo))
        return
      }
    }
    if (action.lesson_id) {
      const selected = lessons.find((lesson) => lesson.lesson_id === action.lesson_id)
      if (selected && action.type === 'learn_lesson') selectLesson(selected)
      else
        navigate(
          `${returnTo}${['practice_lesson', 'review_lesson'].includes(action.type) ? '#course-practice' : ''}`,
        )
    } else
      scrollCourseSection('course-progress-stats', 'center')
  }
  if (courseQuery.isPending) return <Loading>正在恢复课程与学习进度…</Loading>
  if (revoked)
    return (
      <div className="course-page">
        <Link to="/study" className="back-link">
          <ArrowLeft size={16} />
          我的课程
        </Link>
        <PageHeading title="课程资料已失效" description="相关课时、标题和引用已隐藏。" />
        <div className="card">
          <EmptyState
            title="重新选择资料，继续学习"
            action={
              <Link to="/study/courses/new" className="button primary">
                创建新课程
                <ArrowRight size={16} />
              </Link>
            }
          >
            资料可能已被删除或授权已变更。请从当前可用资料重新开始。
          </EmptyState>
        </div>
      </div>
    )
  if (courseQuery.error || !course)
    return (
      <ErrorNotice
        error={courseErrorMessage(courseQuery.error)}
        onRetry={() => {
          void courseQuery.refetch()
        }}
      />
    )
  const outlineTask =
    course.active_task?.kind === 'course_outline'
      ? course.active_task
      : course.latest_task?.kind === 'course_outline'
        ? course.latest_task
        : null
  const showOutlineTask =
    outlineTask &&
    (courseTaskPending(outlineTask) ||
      ['generating', 'failed', 'cancelled'].includes(course.status))
  const availableLessons = lessons.filter(
    (lesson) => lesson.availability !== 'material_gap' && lesson.status !== 'source_revoked',
  )
  return (
    <div className="course-page">
      <Link to="/study" className="back-link">
        <ArrowLeft size={16} />
        我的课程
      </Link>
      <PageHeading
        eyebrow="循课 · 一课一步"
        title={course.title}
        description={course.mission?.goal || '正在整理这门课程的学习目标。'}
        action={
          <Link to="/study/courses/new" className="button secondary">
            <Plus size={16} />
            新课程
          </Link>
        }
      />
      <div className="course-source-label">
        <span className="badge">
          {course.source_policy === 'topic' ? '主题课程' : '仅依据所选资料'}
        </span>
        <span className="tiny muted">
          {course.source_policy === 'topic'
            ? '基于模型通用知识，无已保存的资料引用'
            : `已固定 ${course.scope?.documents?.length || 0} 份资料的版本`}
          {course.mission?.daily_minutes ? ` · 每天 ${course.mission.daily_minutes} 分钟` : ''}
        </span>
        <a className="text-link" href="#course-progress">
          查看学习进度
        </a>
      </div>
      <EvidenceNoticeBar warnings={course.warnings || []} />
      <ErrorNotice
        error={operation.error ? courseErrorMessage(operation.error) : null}
        onRetry={() => invalidate(lessonId || undefined)}
      />
      {showOutlineTask && (
        <>
          <CourseTaskStatus
            courseId={courseId}
            task={outlineTask}
            onRetry={retryOutline}
            disabled={operation.pending !== null}
          />
          <CourseAgentProgress task={outlineTask} teachingMode={course.teaching_mode} />
        </>
      )}
      {course.status === 'ready' || course.status === 'partial' ? (
        <CourseQualityNotice
          summary={course.quality_summary}
          level="outline"
          teachingMode={course.teaching_mode}
        />
      ) : null}
      {!outlineTask && ['failed', 'cancelled'].includes(course.status) && (
        <div className="card">
          <EmptyState
            title="课程纲要尚未完成"
            action={
              <button
                type="button"
                className="button primary"
                disabled={operation.pending !== null}
                onClick={retryOutline}
              >
                重新生成纲要
              </button>
            }
          >
            本课程已保留，可重新生成纲要。
          </EmptyState>
        </div>
      )}
      {!!lessons.length && (
        <div className={`course-workspace${outlineCollapsed ? ' outline-collapsed' : ''}`}>
          <div className="course-outline-column">
          {outlineCollapsed && (
            <button
              id="course-outline-toggle"
              type="button"
              className="outline-rail"
              onClick={toggleOutline}
              aria-label="展开课程目录"
              aria-expanded={false}
              aria-controls="course-outline"
              title="展开课程目录"
            >
              <PanelLeftOpen size={16} />
              <span>课程目录</span>
            </button>
          )}
            <div id="course-outline" hidden={outlineCollapsed}>
              {!outlineCollapsed &&
              <CourseOutline
                course={course}
                selectedLessonId={lessonId}
                onSelect={selectLesson}
                onEvidence={(sourceRef) => setEvidence({ sourceRef })}
                onSave={saveOutline}
                disabled={operation.pending !== null}
                onCollapse={toggleOutline}
              />
              }
            </div>
          </div>
          <div className="course-main">
            {lessonId ? (
              lessonQuery.error ? (
                <ErrorNotice
                  error={courseErrorMessage(lessonQuery.error)}
                  onRetry={() => {
                    void lessonQuery.refetch()
                  }}
                />
              ) : !lessonQuery.data ? (
                <Loading>正在读取这一课…</Loading>
              ) : (
                <>
                <CourseAgentProgress
                  task={lessonQuery.data.active_task || lessonQuery.data.latest_task}
                  teachingMode={course.teaching_mode}
                />
                {lessonQuery.data.status === 'ready' && (
                  <CourseQualityNotice
                    summary={lessonQuery.data.quality_summary}
                    level="lesson"
                    teachingMode={course.teaching_mode}
                  />
                )}
                {['not_generated', 'failed', 'cancelled'].includes(lessonQuery.data.status) &&
                  course.teaching_mode === 'fast' && (
                    <CourseQualityNotice
                      summary={null}
                      level="lesson"
                      teachingMode="fast"
                      onRequestReview={() => generateLesson(lessonId, true)}
                      requestPending={operation.pending === `lesson:${lessonId}`}
                      requestDisabled={operation.pending !== null}
                    />
                  )}
                <CourseLesson
                  key={`${lessonQuery.data.lesson_id}:${lessonQuery.data.content_version}`}
                  lesson={lessonQuery.data}
                  sourcePolicy={course.source_policy}
                  pendingWeakPoints={
                    progressQuery.error ? [] : progressQuery.data?.pending_weak_points || []
                  }
                  progressState={progressQuery.error ? 'unconfirmed' : progressQuery.isPending ? 'loading' : 'confirmed'}
                  nextAction={!progressQuery.error ? progressQuery.data?.next_action : undefined}
                  onNextAction={nextAction}
                  reviews={reviewsQuery.error ? [] : reviewsQuery.data || []}
                  reviewsError={reviewsQuery.error}
                  onReloadReviews={() => {
                    void reviewsQuery.refetch()
                  }}
                  onGenerate={() => generateLesson(lessonId)}
                  onEvidence={(sourceRef) => setEvidence({ sourceRef, lessonId })}
                  onUnavailable={hideSource}
                  generating={operation.pending === `lesson:${lessonId}`}
                />
                </>
              )
            ) : (
              <section className="card course-intro">
                <span className="icon-tile indigo">
                  <BookOpen size={24} />
                </span>
                <h2>先看目标，再开始第一课</h2>
                {!!course.mission?.success_criteria?.length && (
                  <ul>
                    {course.mission?.success_criteria?.map((criterion, index) => (
                      <li key={index}>{criterion}</li>
                    ))}
                  </ul>
                )}
                {!!course.mission?.prior_knowledge?.length && (
                  <p className="muted">课程基础：{course.mission?.prior_knowledge?.join('、')}</p>
                )}
                {availableLessons[0] ? (
                  <button
                    type="button"
                    className="button primary"
                    disabled={operation.pending !== null}
                    onClick={() => selectLesson(availableLessons[0])}
                  >
                    开始学习
                    <ArrowRight size={16} />
                  </button>
                ) : (
                  <p className="notice">当前资料未覆盖可学习课时，请补充资料后创建新课程。</p>
                )}
              </section>
            )}
          </div>
        </div>
      )}
      {!!lessons.length &&
        (progressQuery.error ? (
          <ErrorNotice
            error={courseErrorMessage(progressQuery.error)}
            onRetry={() => {
              void progressQuery.refetch()
            }}
          />
        ) : progressQuery.data ? (
          <CourseProgress
            courseId={courseId}
            progress={progressQuery.data}
            lessons={lessons}
            reviews={reviewsQuery.error ? [] : reviewsQuery.data || []}
            onAction={nextAction}
            onLesson={(id) => navigate(coursePath(courseId, id))}
          />
        ) : (
          <Loading>正在读取学习进度…</Loading>
        ))}
      {!!lessonId && lessonQuery.data?.status === 'ready' && (
        <div className="button-row course-revision-entry">
          <button type="button" className="button secondary" onClick={() => setRevisionOpen(true)}>
            修订这一课
          </button>
          <CourseExportActions courseId={courseId} />
          <button type="button" className="button secondary" onClick={() => setVersionHistoryOpen(true)}>
            版本历史
          </button>
        </div>
      )}
      {versionHistoryOpen && lessonId && (
        <CourseVersionHistory
          courseId={courseId}
          lessonId={lessonId}
          onClose={() => setVersionHistoryOpen(false)}
        />
      )}
      {revisionOpen && lessonId && (
        <CourseRevisionDialog
          courseId={courseId}
          lessons={lessons}
          candidates={lessons.filter((lesson) => lesson.status === 'ready')}
          courseRevision={course.revision}
          criteriaRevision={course.criteria_revision}
          onApplied={() => {
            setRevisionOpen(false)
            invalidate(lessonId)
          }}
          onClose={() => setRevisionOpen(false)}
        />
      )}
      {!!lessons.length && ['ready', 'partial'].includes(course.status) && (
        <CourseAssessmentPanel
          course={course}
          onUnavailable={hideSource}
          onLesson={(id) => {
            const selected = lessons.find((lesson) => lesson.lesson_id === id)
            if (selected) selectLesson(selected)
            else navigate(coursePath(courseId, id))
          }}
          onEvidence={(sourceRef) => setEvidence({ sourceRef })}
        />
      )}
      {evidence && (
        <CourseEvidenceDrawer
          courseId={courseId}
          sourceRef={evidence.sourceRef}
          lessonId={evidence.lessonId}
          onClose={() => setEvidence(null)}
          onUnavailable={hideSource}
        />
      )}
    </div>
  )
}
