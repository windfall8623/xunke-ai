import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpen, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, formatDate } from '../../components/ui'
import { courseErrorMessage, courseKeys, coursesApi } from '../../services/courses'
import { coursePath } from '../../services/courseNavigation'
import type { CourseStatus } from '../../types/course'
import { CourseCover, CourseReadingProgress, courseReadingProgress } from './CourseCover'
import '../../styles/courses.scss'

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
}: {
  compact?: boolean
  showCreate?: boolean
}) {
  const identity = useIdentityKey()
  return <CourseList key={identity} identity={identity} compact={compact} showCreate={showCreate} />
}

function CourseList({
  identity,
  compact,
  showCreate,
}: {
  identity: string | number
  compact: boolean
  showCreate: boolean
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
      <div className="section-line course-shelf-heading">
        <div>
          <h2>我的课程</h2>
          <p className="muted">从上次停下的地方，继续一点点理解。</p>
        </div>
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
        <div className="course-card-grid">
          {query.data.items.map((course) => {
            const revoked = course.source_status === 'revoked' || course.status === 'source_revoked'
            const { read, total: available } = courseReadingProgress(course.lessons)
            const path = coursePath(course.course_id, revoked ? null : course.resume_lesson_id)
            return (
              <article className="course-card" key={course.course_id}>
                <CourseCover course={course} to={path} />
                <div className="course-card-details">
                  <div className="course-card-meta">
                    <span className="tiny muted">
                      {revoked ? '资料已失效' : statusLabels[course.status]}
                    </span>
                    <span className="tiny muted">{formatDate(course.updated_at)}</span>
                  </div>
                  <p className="muted course-card-goal">
                    {revoked
                      ? '相关内容已隐藏，请重新选择资料创建课程。'
                      : course.mission?.goal || '正在将你的学习目标整理成课程纲要。'}
                  </p>
                  {!revoked && (
                    <CourseReadingProgress
                      lessons={course.lessons}
                      label={`${course.title}阅读进度`}
                    />
                  )}
                  <div className="course-card-footer">
                    <span className="tiny muted">
                      {!revoked && !available ? '纲要就绪后可逐课学习' : ''}
                    </span>
                    <Link className="text-link" to={path}>
                      {revoked
                        ? '查看状态'
                        : ['failed', 'cancelled', 'generating'].includes(course.status)
                          ? '查看进度'
                          : read
                            ? '继续学习'
                            : '查看课程'}
                      <ArrowRight size={15} />
                    </Link>
                  </div>
                </div>
              </article>
            )
          })}
        </div>
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
