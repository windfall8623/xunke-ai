import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { StudyScopePicker } from '../../features/study/StudyScopePicker'
import { StudyActivitySummary } from '../../features/study/StudyActivitySummary'
import { LearningHabitCard } from '../../features/study/LearningHabitCard'
import { WeeklySummaryCard } from '../../features/study/WeeklySummaryCard'
import { CourseListSection } from '../../features/courses/CourseListSection'
import { CourseTodayCard } from '../../features/courses/CourseTodayCard'
import { StudyNavigation } from './ReviewPage'
import {
  createStudySubmissionKeys,
  studyApi,
  studyErrorMessage,
  studyKeys,
} from '../../services/study'
import type { SourceScope } from '../../types/api'
import type { StudySpace, StudySpaceCreate } from '../../types/study'

export function StudyHomePage() {
  const identity = useIdentityKey()
  return <StudyHome key={identity} identity={identity} />
}

function StudyHome({ identity }: { identity: string | number }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<StudySpace['status'] | 'all'>('active')
  const [creating, setCreating] = useState(false)
  const filter = status === 'all' ? undefined : status
  const spaces = useQuery({
    queryKey: studyKeys.spaces(identity, page, filter),
    queryFn: ({ signal }) => studyApi.spaces(page, filter, signal),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  return (
    <div className="stack-form" style={{ minWidth: 0 }}>
      <PageHeading
        eyebrow="循课 · 持续学习"
        title="我的学习"
        description="找到原课程，接着读一课、练一组，让每次学习接得上。"
        action={
          <Link className="button secondary" to="/study/courses/new">
            <Plus size={17} />
            开始新课程
          </Link>
        }
      />
      <StudyNavigation />
      <CourseTodayCard />
      <CourseListSection showCreate={false} />
      <StudyActivitySummary />
      <LearningHabitCard />
      <WeeklySummaryCard />
      <div className="section-line">
        <h2>学习空间</h2>
        <button className="button secondary" onClick={() => setCreating(true)}>
          <Plus size={17} />
          新建学习空间
        </button>
      </div>
      <div className="button-row">
        <label>
          显示范围
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as typeof status)
              setPage(1)
            }}
          >
            <option value="active">进行中的空间</option>
            <option value="archived">已归档的空间</option>
            <option value="all">全部空间</option>
          </select>
        </label>
        <Link to="/qa" className="button secondary">
          从资料问答开始练习
        </Link>
      </div>
      {spaces.error ? (
        <ErrorNotice
          error={studyErrorMessage(spaces.error)}
          onRetry={() => {
            void spaces.refetch()
          }}
        />
      ) : !spaces.data ? (
        <Loading>正在读取学习空间…</Loading>
      ) : !spaces.data.items.length ? (
        <EmptyState title="还没有此类学习空间">
          新建空间后，可以整理学习目标；也可以从一条有依据的问答直接创建。
        </EmptyState>
      ) : (
        <div
          style={{
            display: 'grid',
            gap: 16,
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 18rem), 1fr))',
          }}
        >
          {spaces.data.items.map((space) => (
            <article
              className="card"
              key={space.space_id}
              style={{ minWidth: 0, overflowWrap: 'anywhere' }}
            >
              <span className="badge">{space.status === 'archived' ? '已归档' : '进行中'}</span>
              <h2>
                <Link to={`/study/spaces/${encodeURIComponent(space.space_id)}`}>
                  {space.source_status === 'revoked' ? '资料已失效的学习空间' : space.title}
                </Link>
              </h2>
              <p className="muted">
                {space.source_status === 'revoked'
                  ? '来源不可用，相关学习内容已隐藏。'
                  : `${space.scope?.documents?.length || 0} 份资料 · 固定范围版本 ${space.scope_revision}`}
              </p>
              <p className="tiny muted">学习时区：{space.timezone}</p>
            </article>
          ))}
        </div>
      )}
      {spaces.data && !spaces.error && spaces.data.total > spaces.data.page_size && (
        <div className="button-row" aria-label="学习空间分页">
          <button
            className="button secondary"
            disabled={page === 1 || spaces.isFetching}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </button>
          <span>第 {page} 页</span>
          <button
            className="button secondary"
            disabled={page * spaces.data.page_size >= spaces.data.total || spaces.isFetching}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </button>
        </div>
      )}
      {creating && (
        <CreateSpace
          onClose={() => setCreating(false)}
          onCreated={(space) => {
            setCreating(false)
            void client.invalidateQueries({ queryKey: studyKeys.all(identity) })
            navigate(`/study/spaces/${encodeURIComponent(space.space_id)}`)
          }}
        />
      )}
    </div>
  )
}

function CreateSpace({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (space: StudySpace) => void
}) {
  const identity = useIdentityKey()
  const keyFor = useMemo(() => createStudySubmissionKeys(identity, 'home'), [identity])
  const [title, setTitle] = useState('')
  const [timezone, setTimezone] = useState('Asia/Shanghai')
  const [scope, setScope] = useState<SourceScope | null>({
    type: 'selected_documents',
    documents: [],
  })
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (controller.current || !title.trim() || !scope?.documents?.length) return
    const current = new AbortController()
    controller.current = current
    setPending(true)
    setError(null)
    const body: StudySpaceCreate = { title: title.trim(), timezone: timezone.trim(), scope }
    const semantic = JSON.stringify(body)
    try {
      const key = await keyFor('space', semantic)
      if (current.signal.aborted) return
      const created = await studyApi.createSpace(body, key, current.signal)
      if (!current.signal.aborted) {
        keyFor.settle('space', semantic)
        onCreated(created)
      }
    } catch (cause) {
      if (!current.signal.aborted) setError(cause)
    } finally {
      controller.current = null
      if (!current.signal.aborted) setPending(false)
    }
  }
  return (
    <Dialog title="新建学习空间" onClose={onClose} className="wide-dialog">
      <form className="stack-form" onSubmit={submit}>
        <label>
          空间名称
          <input
            required
            maxLength={80}
            value={title}
            disabled={pending}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          学习时区
          <input
            required
            value={timezone}
            disabled={pending}
            onChange={(event) => setTimezone(event.target.value)}
          />
          <small>例如 Asia/Shanghai；用于安排本地日期的复习。</small>
        </label>
        <StudyScopePicker value={scope} onChange={setScope} disabled={pending} />
        {error != null && <ErrorNotice error={studyErrorMessage(error)} />}
        <div className="button-row">
          <button className="button secondary" type="button" disabled={pending} onClick={onClose}>
            取消
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={pending || !title.trim() || !timezone.trim() || !scope?.documents?.length}
          >
            {pending ? '正在创建…' : '创建空间'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
