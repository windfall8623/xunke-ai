import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpen, Plus } from 'lucide-react'
import { Fragment, useEffect, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, formatDate } from '../../components/ui'
import { courseErrorMessage, courseKeys, coursesApi } from '../../services/courses'
import { coursePath } from '../../services/courseNavigation'
import type { CourseStatus, CourseView } from '../../types/course'
import { CourseCover, CourseReadingProgress, courseReadingProgress } from './CourseCover'
import '../../styles/courses.scss'
import '../../styles/course-bookshelf.scss'

function useShelfColumns() {
  const [columns, setColumns] = useState(1)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const desktop = window.matchMedia('(min-width: 1200px)')
    const tablet = window.matchMedia('(min-width: 768px)')
    const update = () => setColumns(desktop.matches ? 3 : tablet.matches ? 2 : 1)
    update()
    desktop.addEventListener('change', update)
    tablet.addEventListener('change', update)
    return () => {
      desktop.removeEventListener('change', update)
      tablet.removeEventListener('change', update)
    }
  }, [])
  return columns
}

const statusLabels: Record<CourseStatus, string> = {
  generating: '纲要准备中',
  ready: '可以学习',
  partial: '部分资料待补充',
  failed: '生成未完成',
  cancelled: '已取消',
  source_revoked: '资料已失效',
}

export function CourseListSection({
  compact = false,
  showCreate = true,
  showHeading = true,
}: {
  compact?: boolean
  showCreate?: boolean
  showHeading?: boolean
}) {
  const identity = useIdentityKey()
  return (
    <CourseList
      key={identity}
      identity={identity}
      compact={compact}
      showCreate={showCreate}
      showHeading={showHeading}
    />
  )
}

function CourseBookshelf({ courses }: { courses: CourseView[] }) {
  const columns = useShelfColumns()
  const detailId = useId()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = courses.find((course) => course.course_id === selectedId) ?? courses[0]
  const rows = Array.from({ length: Math.ceil(courses.length / columns) }, (_, index) =>
    courses.slice(index * columns, (index + 1) * columns),
  )
  if (!selected) return null
  const revoked = selected.source_status === 'revoked' || selected.status === 'source_revoked'
  const { read, total: available } = courseReadingProgress(selected.lessons)
  const path = coursePath(selected.course_id, revoked ? null : selected.resume_lesson_id)

  const detail = (
    <section
      id={detailId}
      className="course-bookshelf-detail"
      aria-labelledby={`${detailId}-title`}
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="course-bookshelf-detail-copy">
        <div className="course-bookshelf-detail-meta tiny muted">
          <span>{revoked ? '资料已失效' : statusLabels[selected.status]}</span>
          <span>{formatDate(selected.updated_at)}</span>
        </div>
        <h3 id={`${detailId}-title`}>{revoked ? '资料已失效的课程' : selected.title}</h3>
        <p className="muted">
          {revoked
            ? '相关内容已隐藏，请重新选择资料创建课程。'
            : selected.mission?.goal || '正在将你的学习目标整理成课程纲要。'}
        </p>
      </div>
      <div className="course-bookshelf-detail-actions">
        {!revoked && (
          <CourseReadingProgress lessons={selected.lessons} label={`${selected.title}阅读进度`} />
        )}
        {!revoked && !available && <p className="tiny muted">纲要就绪后可逐课学习</p>}
        <Link className="button primary" to={path}>
          {revoked
            ? '查看状态'
            : ['failed', 'cancelled', 'generating'].includes(selected.status)
              ? '查看进度'
              : read
                ? '继续学习'
                : '查看课程'}
          <ArrowRight size={15} />
        </Link>
      </div>
    </section>
  )
  return (
    <div className="course-bookshelf-layout">
      <p className="course-bookshelf-hint muted">选一本课程，查看学习目标与阅读进度。</p>
      <div className="course-bookshelf" role="group" aria-label="选择课程">
        {rows.map((row, index) => (
          <Fragment key={index}>
            <div
              className="course-bookshelf-row"
              style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
            >
              {row.map((course) => (
                <CourseCover
                  key={course.course_id}
                  course={course}
                  onSelect={() => setSelectedId(course.course_id)}
                  selected={selected.course_id === course.course_id}
                  controls={detailId}
                />
              ))}
            </div>
            {columns === 1 &&
              row.some((course) => course.course_id === selected.course_id) &&
              detail}
          </Fragment>
        ))}
      </div>
      {columns > 1 && detail}
    </div>
  )
}

function CourseList({
  identity,
  compact,
  showCreate,
  showHeading,
}: {
  identity: string | number
  compact: boolean
  showCreate: boolean
  showHeading: boolean
}) {
  const auth = useAuth()
  const [page, setPage] = useState(1)
  const pageSize = compact ? 3 : 6
  const query = useQuery({
    queryKey: courseKeys.list(identity, page, pageSize),
    queryFn: ({ signal }) => coursesApi.list(page, pageSize, signal),
    enabled: auth.status === 'authenticated',
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) =>
      state.state.data?.items.some((course) => course.status === 'generating') ? 4000 : false,
    refetchIntervalInBackground: false,
  })
  return (
    <section className="course-shelf" aria-label="我的课程">
      {(showHeading || showCreate || (compact && auth.status === 'authenticated')) && (
        <div className="section-line course-shelf-heading">
          {showHeading && (
            <div>
              <h2>我的课程</h2>
              <p className="muted">从上次停下的地方，继续一点点理解。</p>
            </div>
          )}
          <div className="button-row">
            {compact && auth.status === 'authenticated' && (
              <Link to="/study" className="text-link">
                全部课程
                <ArrowRight size={14} />
              </Link>
            )}
            {showCreate && (
              <Link className="button primary" to="/study/courses/new">
                <Plus size={17} />
                开始新课程
              </Link>
            )}
          </div>
        </div>
      )}
      {auth.status === 'initializing' ? (
        <Loading>正在恢复课程…</Loading>
      ) : auth.status !== 'authenticated' ? (
        <div className="card course-welcome">
          <BookOpen size={32} />
          <div>
            <h3>把想学的内容，变成一门自己的课程。</h3>
            <p className="muted">
              主题或资料都可以开始。登录后，纲要、阅读和练习记录会保存到你的账号。
            </p>
          </div>
          <Link className="button secondary" to="/study/courses/new">
            登录并开始
            <ArrowRight size={16} />
          </Link>
        </div>
      ) : query.error ? (
        <ErrorNotice
          error={courseErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : query.isPending ? (
        <Loading>正在读取我的课程…</Loading>
      ) : !query.data?.items.length ? (
        <div className="card">
          <EmptyState title="从第一门课程开始">
            告诉循课你想学什么，先看纲要，再逐课学习与练习。
          </EmptyState>
        </div>
      ) : (
        <CourseBookshelf key={page} courses={query.data.items} />
      )}
      {!compact && query.data && !query.error && query.data.total > pageSize && (
        <div className="button-row course-pagination" aria-label="课程分页">
          <button
            type="button"
            className="button secondary"
            disabled={page === 1 || query.isFetching}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </button>
          <span>第 {page} 页</span>
          <button
            type="button"
            className="button secondary"
            disabled={page * pageSize >= query.data.total || query.isFetching}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </section>
  )
}
