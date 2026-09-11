import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading } from '../../components/ui'
import { studyApi, studyErrorMessage, studyKeys } from '../../services/study'
import { AttemptTimeline, studyDate } from './AttemptTimeline'

export function StudyActivitySummary() {
  const identity = useIdentityKey()
  const filters = { limit: 3 }
  const reviews = useQuery({
    queryKey: studyKeys.reviews(identity, filters),
    queryFn: ({ signal }) => studyApi.reviews(filters, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
  const history = useQuery({
    queryKey: studyKeys.history(identity, filters),
    queryFn: ({ signal }) => studyApi.history(filters, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
  return (
    <>
      <section className="card stack-form" aria-label="当前复习">
        <div className="button-row">
          <h2>当前待复习</h2>
          <Link className="text-button" to="/study/reviews">
            查看全部复习安排
          </Link>
        </div>
        {reviews.error ? (
          <ErrorNotice
            error={studyErrorMessage(reviews.error)}
            onRetry={() => {
              void reviews.refetch()
            }}
          />
        ) : !reviews.data ? (
          <Loading>正在读取复习安排…</Loading>
        ) : !reviews.data.items.length ? (
          <p className="muted">当前没有到期复习，可以开始新的学习。</p>
        ) : (
          <ul className="study-record-list">
            {reviews.data.items.map((item) => (
              <li key={item.review_task_id}>
                {item.source_status === 'revoked' ? (
                  '资料已失效的复习'
                ) : (
                  <Link to={`/study/reviews?concept_id=${encodeURIComponent(item.concept_id)}`}>
                    {item.concept_title} · {studyDate(item.due_at, item.timezone)}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="stack-form" aria-label="最近学习">
        <div className="button-row">
          <h2>最近学习</h2>
          <Link className="text-button" to="/study/history">
            查看全部学习记录
          </Link>
        </div>
        {history.error ? (
          <ErrorNotice
            error={studyErrorMessage(history.error)}
            onRetry={() => {
              void history.refetch()
            }}
          />
        ) : !history.data ? (
          <Loading>正在读取最近学习…</Loading>
        ) : (
          <AttemptTimeline items={history.data.items} />
        )}
      </section>
    </>
  )
}
