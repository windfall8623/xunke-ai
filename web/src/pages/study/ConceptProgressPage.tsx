import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { AttemptTimeline, studyDate } from '../../features/study/AttemptTimeline'
import { studyApi, studyErrorMessage, studyKeys } from '../../services/study'
import { StudyNavigation } from './ReviewPage'

const stages = ['需要练习', '开始建立理解', '继续巩固', '多次表现稳定', '近期表现稳定']
export function ConceptProgressPage() {
  const identity = useIdentityKey()
  const { conceptId = '' } = useParams()
  const query = useQuery({
    queryKey: studyKeys.progress(identity, conceptId),
    queryFn: ({ signal }) => studyApi.conceptProgress(conceptId, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  if (query.error)
    return (
      <ErrorNotice
        error={studyErrorMessage(query.error)}
        onRetry={() => {
          void query.refetch()
        }}
      />
    )
  if (!query.data) return <Loading>正在读取概念进度…</Loading>
  const progress = query.data
  if (progress.source_status !== 'active')
    return <EmptyState title="资料已失效">相关概念和学习内容已隐藏。</EmptyState>
  return (
    <div className="stack-form">
      <PageHeading
        eyebrow="循课 · 概念进度"
        title={progress.title}
        description="根据已完成活动中的独立学习证据展示阶段；它不是永久掌握程度。"
      />
      <StudyNavigation />
      <div className="button-row">
        <Link
          className="button secondary"
          to={`/study/spaces/${encodeURIComponent(progress.space_id)}`}
        >
          返回所属空间
        </Link>
        <Link
          className="button primary"
          to={`/study/reviews?concept_id=${encodeURIComponent(conceptId)}`}
        >
          查看复习安排
        </Link>
        <Link
          className="button secondary"
          to={`/study/wrong-questions?space_id=${encodeURIComponent(progress.space_id)}&concept_id=${encodeURIComponent(conceptId)}`}
        >
          相关错题
        </Link>
      </div>
      {!progress.states.length ? (
        <EmptyState title="尚无已确认的学习证据">
          完成关联练习并确认评分后，会在这里显示阶段和复习安排。
        </EmptyState>
      ) : (
        <div className="study-card-grid">
          {progress.states.map((state) => (
            <section className="card stack-form" key={state.scope_revision}>
              <span className="tiny muted">资料范围版本 {state.scope_revision}</span>
              <h2>{stages[state.stage]}</h2>
              <p>独立学习证据：{state.evidence_count} 次</p>
              <p>
                下次复习：{studyDate(state.due_at)}
                {state.paused ? '（已暂停）' : ''}
              </p>
              <p className="tiny muted">
                最近学习日期：{state.last_activity_local_date || '暂无'}
                {state.override_due_at ? ' · 已手动调整复习时间' : ''}
              </p>
            </section>
          ))}
        </div>
      )}
      <h2>最近学习</h2>
      <AttemptTimeline items={progress.recent_history} />
      {progress.history_next_cursor && (
        <Link
          to={`/study/history?space_id=${encodeURIComponent(progress.space_id)}&concept_id=${encodeURIComponent(conceptId)}`}
          className="button secondary"
        >
          查看完整时间线
        </Link>
      )}
    </div>
  )
}
