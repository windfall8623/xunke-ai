import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../components/ui'
import { AnswerInput, emptyPracticeAnswer } from '../features/practice/AnswerInput'
import { AssessmentFeedback } from '../features/practice/AssessmentFeedback'
import { PracticeEvidencePanel } from '../features/practice/PracticeEvidencePanel'
import { PracticeAttemptActions } from '../features/practice/PracticeAttemptActions'
import {
  usePracticeProgress,
  type PendingPracticeAnswer,
} from '../features/practice/usePracticeProgress'
import { markPracticeHelp, practiceErrorMessage } from '../services/practice'
import type { PracticeAnswer, PracticeAttempt, PracticeQuestion } from '../types/practice'

export function PracticePage() {
  const { practiceId = '' } = useParams()
  const identity = useIdentityKey()
  return <PracticeContent key={`${identity}:${practiceId}`} practiceId={practiceId} />
}
function PracticeContent({ practiceId }: { practiceId: string }) {
  const { practiceQuery, answerMutation, completion, pendingAnswers } =
    usePracticeProgress(practiceId)
  if (practiceQuery.error)
    return (
      <ErrorNotice
        error={practiceErrorMessage(practiceQuery.error)}
        onRetry={() => {
          void practiceQuery.refetch()
        }}
      />
    )
  const practice = practiceQuery.data
  if (!practice) return <Loading>正在恢复练习进度…</Loading>
  if (practice.source_status !== 'active')
    return <EmptyState title="资料已失效">相关练习和作答内容已隐藏。</EmptyState>
  const questions = practice.questions || []
  const submissions = practice.submissions || []
  const allSubmitted = questions.length > 0 && practice.submitted_count === questions.length
  return (
    <div className="narrow-page stack-form">
      <Link className="back-link" to={`/study/spaces/${encodeURIComponent(practice.space_id)}`}>
        返回所属学习空间
      </Link>
      <PageHeading
        eyebrow="知学 AI · 综合练习"
        title={practice.title}
        description={practice.summary}
      />
      <p className="muted">
        已作答 {practice.submitted_count}/{questions.length} 题 · 已确认评分{' '}
        {practice.confirmed_count} 题
        {practice.pending_grading_count ? ` · ${practice.pending_grading_count} 题正在评分` : ''}
        {practice.needs_review_count ? ` · ${practice.needs_review_count} 题待复核` : ''}
      </p>
      {practice.status === 'generating' && <Loading>题目仍在生成…</Loading>}
      {['failed', 'cancelled'].includes(practice.status) && (
        <p className="notice">练习生成未完成，请返回学习空间重新创建。</p>
      )}
      {questions.map((question, index) => (
        <PracticeQuestionCard
          key={question.id}
          practiceId={practiceId}
          question={question}
          index={index}
          attempt={submissions.find((item) => item.question_id === question.id)}
          pending={pendingAnswers[question.id]}
          submitting={answerMutation.isPending}
          disabled={practice.status !== 'ready'}
          onSubmit={(answer, duration) => answerMutation.mutate({ question, answer, duration })}
        />
      ))}
      {answerMutation.error && <ErrorNotice error={practiceErrorMessage(answerMutation.error)} />}
      {completion.error && <ErrorNotice error={practiceErrorMessage(completion.error)} />}
      {practice.status === 'ready' && (
        <button
          className="button primary"
          disabled={!allSubmitted || answerMutation.isPending || completion.isPending}
          onClick={() => completion.mutate()}
        >
          {completion.isPending ? '正在保存…' : '完成作答'}
        </button>
      )}
      {practice.status === 'completed' && (
        <section className="card stack-form" role="status">
          <h2>作答已保存</h2>
          <p>
            {practice.confirmed_count < questions.length
              ? '部分评分尚待确认，你的答案已完整保存。'
              : practice.projection_status === 'pending'
                ? '学习记录已保存，统计正在更新。'
                : practice.projection_status === 'failed'
                  ? '学习记录已保存，统计更新暂未完成。'
                  : '本次练习已完成，可到学习空间查看复习安排。'}
          </p>
          <Link className="button secondary" to="/study/reviews">
            查看复习安排
          </Link>
        </section>
      )}
      <button
        className="text-button"
        onClick={() => {
          void practiceQuery.refetch()
        }}
      >
        刷新已保存的进度
      </button>
    </div>
  )
}

function PracticeQuestionCard({
  practiceId,
  question,
  index,
  attempt,
  pending,
  submitting,
  disabled,
  onSubmit,
}: {
  practiceId: string
  question: PracticeQuestion
  index: number
  attempt?: PracticeAttempt
  pending?: PendingPracticeAnswer
  submitting: boolean
  disabled: boolean
  onSubmit: (answer: PracticeAnswer, duration: number) => void
}) {
  const [answer, setAnswer] = useState<PracticeAnswer>(() => emptyPracticeAnswer(question))
  const [startedAt] = useState(Date.now)
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const [helpPending, setHelpPending] = useState(false)
  const [helpError, setHelpError] = useState<unknown>(null)
  const value = attempt?.answer || pending?.body.answer || answer
  const stem =
    question.type === 'cloze'
      ? question.blank_ids.reduce(
          (text, blankId, blankIndex) =>
            text.replaceAll(`{{${blankId}}}`, `（${blankIndex + 1}）____`),
          question.stem,
        )
      : question.stem
  return (
    <section className="card stack-form" data-testid={`practice-question-${question.id}`}>
      <span className="badge">
        第 {index + 1} 题 ·{' '}
        {({ cloze: '填空', numeric: '数值', short_answer: '短解释' } as const)[question.type]}
      </span>
      <h2>{stem}</h2>
      <div className="button-row">
        {question.citation_refs.map((id, citationIndex) => (
          <button
            className="text-button"
            key={id}
            disabled={helpPending || submitting}
            onClick={async () => {
              setHelpPending(true)
              setHelpError(null)
              try {
                if (!attempt) await markPracticeHelp(practiceId, question.id)
                setEvidenceId(id)
              } catch (cause) {
                setHelpError(cause)
              } finally {
                setHelpPending(false)
              }
            }}
          >
            {attempt ? '查看依据' : '查看资料提示'} {citationIndex + 1}
          </button>
        ))}
      </div>
      {!attempt && <p className="tiny muted">查看资料提示会记录为辅助作答，不计为独立练习证据。</p>}
      {helpError != null && <ErrorNotice error={practiceErrorMessage(helpError)} />}
      {evidenceId && (
        <PracticeEvidencePanel
          practiceId={practiceId}
          questionId={question.id}
          evidenceId={evidenceId}
          onClose={() => setEvidenceId(null)}
        />
      )}
      <form
        className="stack-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (!attempt && !submitting && !disabled) onSubmit(value, Date.now() - startedAt)
        }}
      >
        <AnswerInput
          question={question}
          value={value}
          onChange={setAnswer}
          disabled={!!attempt || !!pending || submitting || disabled}
        />
        {pending && !attempt && (
          <p className="notice">上次提交的结果尚未确认，重试会使用原答案和同一请求。</p>
        )}
        {!attempt && (
          <button className="button primary" disabled={submitting || disabled} type="submit">
            {submitting ? '正在提交…' : pending ? '重试原提交' : '提交答案'}
          </button>
        )}
      </form>
      {attempt && (
        <>
          <AssessmentFeedback
            assessment={
              ['pending', 'running'].includes(attempt.grading_status || '')
                ? null
                : attempt.current_assessment || null
            }
            jobStatus={attempt.grading_status}
          />
          <PracticeAttemptActions attempt={attempt} />
        </>
      )}
    </section>
  )
}
