import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CalendarCheck, Clock3, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading } from '../../components/ui'
import { courseTodayPath } from '../../services/courseNavigation'
import { courseErrorMessage, courseKeys, courseLocalDate, coursesApi } from '../../services/courses'
import type { CourseTodayItem } from '../../types/course'
import '../../styles/courses.scss'

const labels: Record<CourseTodayItem['kind'], string> = {
  continue_quiz: '接着练习',
  course_review: '课时复习',
  study_review: '学习空间复习',
  learn_lesson: '继续学习',
  practice_lesson: '本课练习',
  review_lesson: '待补练',
}

export function CourseTodayCard() {
  const identity = useIdentityKey()
  const [timezone] = useState(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
    } catch {
      return 'Asia/Shanghai'
    }
  })
  const [minutes, setMinutes] = useState(20)
  const [localDate, setLocalDate] = useState(() => courseLocalDate(new Date(), timezone))
  useEffect(() => {
    const refreshDate = () => setLocalDate(courseLocalDate(new Date(), timezone))
    const timer = window.setInterval(refreshDate, 30_000)
    window.addEventListener('focus', refreshDate)
    document.addEventListener('visibilitychange', refreshDate)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refreshDate)
      document.removeEventListener('visibilitychange', refreshDate)
    }
  }, [timezone])
  const query = useQuery({
    queryKey: courseKeys.today(identity, timezone, minutes, localDate),
    queryFn: ({ signal }) => coursesApi.today(timezone, minutes, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
  })
  return (
    <section className="card course-today-card" aria-label="今日学习建议">
      <div className="section-line course-today-heading">
        <div>
          <span className="eyebrow">
            <CalendarCheck size={15} />
            今日学习
          </span>
          <h2>从这一小步开始</h2>
          <p className="tiny muted">
            {query.data?.local_date || localDate} · {timezone}
          </p>
        </div>
        <div className="button-row">
          <label className="course-today-budget">
            今天可用时间
            <select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
              {[5, 10, 20, 30, 45, 60, 90, 120].map((value) => (
                <option key={value} value={value}>
                  {value} 分钟
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="icon-button"
            aria-label="刷新今日学习建议"
            disabled={query.isFetching}
            onClick={() => {
              void query.refetch()
            }}
          >
            <RefreshCw size={17} />
          </button>
        </div>
      </div>
      {query.error ? (
        <ErrorNotice
          error={courseErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : query.isPending ? (
        <Loading>正在整理今天可继续的学习…</Loading>
      ) : query.data ? (
        <>
          {query.data.items?.length ? (
            <ol className="course-today-items">
              {query.data.items.map((item, index) => {
                const path = courseTodayPath(item)
                return (
                  <li
                    className="course-today-item"
                    key={`${item.kind}:${item.quiz_id || item.task_id || item.review_id || item.review_task_id || item.lesson_id || index}`}
                  >
                    <span className="course-today-number">{index + 1}</span>
                    <div className="course-today-content">
                      <span className="badge">{labels[item.kind]}</span>
                      <h3>{item.title}</h3>
                      <p className="muted">{item.reason}</p>
                      <p className="tiny muted">
                        <Clock3 size={13} />
                        预计 {item.estimated_minutes} 分钟
                      </p>
                    </div>
                    {path ? (
                      <Link className={`button ${index === 0 ? 'primary' : 'secondary'}`} to={path}>
                        开始
                        <ArrowRight size={16} />
                      </Link>
                    ) : (
                      <span className="tiny muted">请刷新后查看入口</span>
                    )}
                  </li>
                )
              })}
            </ol>
          ) : (
            <p className="muted">今天暂无待处理的学习建议。可以回看已学课时，或开始一门新课程。</p>
          )}
          {!!query.data.warnings?.length && (
            <div className="course-today-notes">
              {query.data.warnings.map((warning, index) => (
                <p className="tiny muted" key={index}>
                  {warning}
                </p>
              ))}
            </div>
          )}
          <p className="tiny muted">预计时长用于安排节奏，实际进度以已保存的阅读与作答为准。</p>
        </>
      ) : null}
    </section>
  )
}
