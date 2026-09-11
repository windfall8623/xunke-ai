import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { ReviewQueue } from '../../features/study/ReviewQueue'
import { generateReviewPractice, practiceErrorMessage } from '../../services/practice'
import {
  createStudySubmissionKeys,
  studyApi,
  studyConflict,
  studyErrorMessage,
  studyKeys,
  studyUnavailable,
} from '../../services/study'
import type { StudyReview, StudyReviewQuiz, StudyReviewUpdate } from '../../types/study'
import type { PracticeSpec } from '../../types/practice'

export function ReviewPage() {
  const identity = useIdentityKey()
  const [params] = useSearchParams()
  const spaceId = params.get('space_id') || undefined
  const conceptId = params.get('concept_id') || undefined
  return (
    <Reviews key={`${identity}:${spaceId}:${conceptId}`} spaceId={spaceId} conceptId={conceptId} />
  )
}

function Reviews({ spaceId, conceptId }: { spaceId?: string; conceptId?: string }) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [cursor, setCursor] = useState<string>()
  const [paused, setPaused] = useState(false)
  const [questionCount, setQuestionCount] = useState(5)
  const [practiceType, setPracticeType] = useState<
    'quiz' | 'cloze' | 'numeric' | 'short_answer' | 'mixed_practice'
  >('quiz')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const inFlight = useRef<AbortController | null>(null)
  const keyFor = useMemo(() => createStudySubmissionKeys(identity, 'reviews'), [identity])
  const filters = {
    space_id: spaceId,
    concept_id: conceptId,
    paused,
    cursor,
    ...(paused ? { due_before: '2100-01-01T00:00:00Z' } : {}),
  }
  const query = useQuery({
    queryKey: studyKeys.reviews(identity, filters),
    queryFn: ({ signal }) => studyApi.reviews(filters, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  useEffect(() => () => inFlight.current?.abort(), [])
  async function start(review: StudyReview) {
    if (inFlight.current) return
    const controller = new AbortController()
    inFlight.current = controller
    setPending(true)
    setError(null)
    const baseBody: StudyReviewQuiz = {
      review_task_ids: [review.review_task_id],
      expected_revisions: { [review.review_task_id]: review.revision },
      question_count: questionCount,
      difficulty: 'mixed',
    }
    const questionTypes: PracticeSpec['question_types'] =
      practiceType === 'mixed_practice'
        ? ['cloze', 'numeric', 'short_answer']
        : practiceType === 'quiz'
          ? []
          : [practiceType]
    const body = practiceType === 'quiz' ? baseBody : { ...baseBody, question_types: questionTypes }
    const semantic = JSON.stringify(body)
    try {
      const key = await keyFor('quiz', semantic)
      if (controller.signal.aborted) return
      const task =
        practiceType === 'quiz'
          ? await studyApi.reviewQuiz(baseBody, key, controller.signal)
          : await generateReviewPractice(
              { ...baseBody, question_types: questionTypes },
              key,
              controller.signal,
            )
      if (!controller.signal.aborted) {
        keyFor.settle('quiz', semantic)
        void client.invalidateQueries({ queryKey: studyKeys.all(identity) })
        navigate(
          practiceType === 'quiz'
            ? `/tasks/${encodeURIComponent(task.task_id)}?returnTo=/study/reviews`
            : `/practice/tasks/${encodeURIComponent(task.task_id)}`,
        )
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause)
        if (studyConflict(cause) || studyUnavailable(cause)) await query.refetch()
      }
    } finally {
      inFlight.current = null
      if (!controller.signal.aborted) setPending(false)
    }
  }
  async function update(review: StudyReview, action: StudyReviewUpdate['action'], dueAt?: string) {
    if (inFlight.current) return
    const controller = new AbortController()
    inFlight.current = controller
    setPending(true)
    setError(null)
    try {
      await studyApi.updateReview(
        review.review_task_id,
        { expected_revision: review.revision, action, ...(dueAt ? { due_at: dueAt } : {}) },
        controller.signal,
      )
      if (!controller.signal.aborted)
        await client.invalidateQueries({ queryKey: studyKeys.all(identity) })
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause)
        if (studyConflict(cause) || studyUnavailable(cause)) await query.refetch()
      }
    } finally {
      inFlight.current = null
      if (!controller.signal.aborted) setPending(false)
    }
  }
  return (
    <div className="stack-form">
      <PageHeading
        eyebrow="知学 AI · 持续学习"
        title="复习安排"
        description="按已确认的学习记录安排复习；完成整套作答后才更新这次复习。"
      />
      <StudyNavigation />
      <div className="button-row">
        <label>
          复习题型
          <select
            value={practiceType}
            disabled={pending}
            onChange={(event) => setPracticeType(event.target.value as typeof practiceType)}
          >
            <option value="quiz">客观题</option>
            <option value="cloze">填空题</option>
            <option value="numeric">数值题</option>
            <option value="short_answer">短解释</option>
            <option value="mixed_practice">填空、数值与短解释</option>
          </select>
        </label>
        <label>
          复习列表
          <select
            value={paused ? 'paused' : 'due'}
            disabled={pending}
            onChange={(event) => {
              setPaused(event.target.value === 'paused')
              setCursor(undefined)
              setError(null)
            }}
          >
            <option value="due">当前待复习</option>
            <option value="paused">已暂停</option>
          </select>
        </label>
        <label>
          每次题量
          <input
            type="number"
            min={3}
            max={10}
            value={questionCount}
            disabled={pending}
            onChange={(event) =>
              setQuestionCount(Math.max(3, Math.min(10, Number(event.target.value) || 3)))
            }
          />
        </label>
      </div>
      {error != null && (
        <ErrorNotice
          error={
            studyConflict(error)
              ? '复习安排或关联任务已更新，请核对刷新后的状态。'
              : practiceErrorMessage(error)
          }
        />
      )}
      {query.error ? (
        <ErrorNotice
          error={studyErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : !query.data ? (
        <Loading>正在读取复习安排…</Loading>
      ) : (
        <ReviewQueue
          items={query.data.items}
          pending={pending}
          onStart={(review) => {
            void start(review)
          }}
          onUpdate={(review, action, due) => {
            void update(review, action, due)
          }}
        />
      )}
      {query.data && (
        <div className="button-row">
          <button
            className="button secondary"
            disabled={!cursor || pending}
            onClick={() => setCursor(undefined)}
          >
            返回第一页
          </button>
          {query.data.next_cursor && (
            <button
              className="button secondary"
              disabled={pending}
              onClick={() => setCursor(query.data!.next_cursor!)}
            >
              下一页
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function StudyNavigation() {
  return (
    <nav className="button-row" aria-label="学习功能">
      <Link className="button secondary" to="/study">
        学习空间
      </Link>
      <Link className="button secondary" to="/study/reviews">
        复习安排
      </Link>
      <Link className="button secondary" to="/study/wrong-questions">
        错题本
      </Link>
      <Link className="button secondary" to="/study/history">
        学习历史
      </Link>
    </nav>
  )
}
