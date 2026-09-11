import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  CircleHelp,
  FileText,
  Image,
  LockKeyhole,
  XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ErrorNotice, Loading, StatusBadge, safeImageUrl } from '../components/ui'
import { useQuizProgress } from '../features/quiz/useQuizProgress'
import { EvidencePanel } from '../features/evidence/EvidencePanel'
import { FeedbackForm } from '../features/quiz/FeedbackForm'
import { safeCourseReturn, withCourseReturn } from '../services/courseNavigation'

export function QuizPage() {
  const { quizId = '' } = useParams()
  const [params] = useSearchParams()
  const courseReturn = safeCourseReturn(params.get('returnTo'))
  const reportPath = withCourseReturn(`/quizzes/${encodeURIComponent(quizId)}/report`, courseReturn)
  const { quizQuery, answerMutation, completion } = useQuizProgress(quizId)
  const quiz = quizQuery.data
  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [evidence, setEvidence] = useState<string | null>(null)
  const [feedback, setFeedback] = useState(false)
  const started = useRef(performance.now())
  const initialized = useRef(false)
  const navigate = useNavigate()
  useEffect(() => {
    if (quiz && !initialized.current) {
      const requested = params.get('question')
      const questionIndex = requested
        ? quiz.questions.findIndex((question) => question.id === requested)
        : quiz.questions.findIndex(
            (question) =>
              !(quiz.answer_records || []).some((answer) => answer.question_id === question.id),
          )
      setIndex(Math.max(0, questionIndex))
      initialized.current = true
    }
  }, [quiz, params])
  const question = quiz?.questions[index]
  const saved = (quiz?.answer_records || []).find((answer) => answer.question_id === question?.id)
  useEffect(() => {
    setSelected(saved?.selected_answers || [])
    started.current = performance.now()
  }, [question?.id, saved])
  if (quizQuery.isPending) return <Loading>正在恢复学习进度…</Loading>
  if (quizQuery.error || !quiz || !question)
    return (
      <ErrorNotice
        error={quizQuery.error || '这组练习暂时无法读取'}
        onRetry={() => {
          void quizQuery.refetch()
        }}
      />
    )
  const answered = quiz.answered_count ?? (quiz.answer_records || []).length
  const allAnswered = answered === quiz.questions.length
  const settled = ['settled', 'completed'].includes(quiz.status)
  const typeLabel = { single: '单选题', multiple: '多选题', judge: '判断题' }[question.type]
  const citations = [...new Set(saved?.citation_refs || question.citation_refs || [])]
  return (
    <div className="quiz-page">
      <div className="quiz-topline">
        <Link to={courseReturn || '/me'} className="back-link">
          <ArrowLeft size={16} />
          {courseReturn ? '返回本课' : '学习记录'}
        </Link>
        <div>
          <StatusBadge status={quiz.source_policy} />
          <StatusBadge status={quiz.source_status} />
        </div>
      </div>
      <header className="quiz-heading">
        <div>
          <p className="eyebrow">专注此刻，一题一收获</p>
          <h1>{quiz.title}</h1>
          <p className="muted">{quiz.summary}</p>
        </div>
        <div className="quiz-progress-summary">
          <strong>
            <span data-testid="answered-count">{answered}</span>
            <span className="muted"> / {quiz.questions.length}</span>
          </strong>
          <span>已保存作答</span>
        </div>
      </header>
      <div
        className="progress-track"
        aria-label={`已保存 ${answered} / ${quiz.questions.length} 题`}
      >
        <span style={{ width: `${(answered / quiz.questions.length) * 100}%` }} />
      </div>
      <div className="quiz-grid">
        <section className="card question-card">
          <div className="question-meta">
            <span className="badge question-type">{typeLabel}</span>
            <span>{question.knowledge_point}</span>
            <span className="question-number">
              {String(index + 1).padStart(2, '0')}{' '}
              <span>/ {String(quiz.questions.length).padStart(2, '0')}</span>
            </span>
          </div>
          <h2>{question.stem}</h2>
          {question.type === 'multiple' && <p className="tiny muted">请选择所有正确选项。</p>}
          {safeImageUrl(question.image_url) && (
            <img
              className="question-image"
              src={safeImageUrl(question.image_url)}
              alt="本题辅助配图"
              loading="lazy"
            />
          )}
          <fieldset
            className="answer-options"
            disabled={!!saved || answerMutation.isPending || settled}
          >
            <legend className="sr-only">选择答案</legend>
            {question.options.map((option) => {
              const checked = selected.includes(option.key)
              const correct = !!saved?.correct_answers?.includes(option.key)
              return (
                <label
                  key={option.key}
                  className={`answer-option ${checked ? 'selected' : ''} ${saved && correct ? 'correct' : ''} ${saved && checked && !saved.is_correct && !correct ? 'incorrect' : ''}`}
                >
                  <input
                    type={question.type === 'multiple' ? 'checkbox' : 'radio'}
                    name={question.id}
                    value={option.key}
                    checked={checked}
                    onChange={() =>
                      setSelected((current) =>
                        question.type === 'multiple'
                          ? checked
                            ? current.filter((key) => key !== option.key)
                            : [...current, option.key]
                          : [option.key],
                      )
                    }
                  />
                  <span className="option-key">{option.key}</span>
                  <span>{option.text}</span>
                  {saved && correct && <Check size={19} className="answer-check" />}
                </label>
              )
            })}
          </fieldset>
          <ErrorNotice error={answerMutation.error} />
          {saved && (
            <div
              className={`answer-feedback ${saved.is_correct ? 'is-correct' : 'is-incorrect'}`}
              role="status"
            >
              <div className="feedback-heading">
                {saved.is_correct ? <CheckCircle2 size={21} /> : <XCircle size={21} />}
                <strong>{saved.is_correct ? '回答正确' : '这题再想一想'}</strong>
                {saved.correct_answers && <span>正确答案：{saved.correct_answers.join('、')}</span>}
              </div>
              <p>{saved.explanation || '这道题的作答已保存。'}</p>
              <span className="tiny">
                <LockKeyhole size={12} />
                已提交的答案仅供回看
              </span>
            </div>
          )}
          <div className="question-actions">
            <button
              type="button"
              className="button secondary"
              disabled={index === 0 || answerMutation.isPending}
              onClick={() => {
                setIndex(index - 1)
                answerMutation.reset()
              }}
            >
              <ArrowLeft size={16} />
              上一题
            </button>
            {!saved && !settled ? (
              <button
                className="button primary"
                disabled={!selected.length || answerMutation.isPending}
                onClick={() => {
                  if (!answerMutation.isPending)
                    answerMutation.mutate({
                      questionId: question.id,
                      selected: [...selected].sort(),
                      duration: performance.now() - started.current,
                    })
                }}
              >
                {answerMutation.isPending ? '正在保存…' : '提交答案'}
                <Check size={16} />
              </button>
            ) : index < quiz.questions.length - 1 ? (
              <button
                type="button"
                className="button primary"
                onClick={() => {
                  setIndex(index + 1)
                  answerMutation.reset()
                }}
              >
                下一题
                <ArrowRight size={16} />
              </button>
            ) : settled ? (
              <Link className="button secondary" to={reportPath}>
                查看报告
                <ArrowRight size={16} />
              </Link>
            ) : null}
          </div>
          {allAnswered && (
            <div className="complete-strip">
              <div>
                <CheckCircle2 size={18} />
                <span>
                  {settled
                    ? '这组练习已完成，欢迎随时回看。'
                    : '所有作答已保存，准备看看你的收获。'}
                </span>
              </div>
              {settled ? (
                <Link to={reportPath} className="button primary">
                  查看学习报告
                </Link>
              ) : (
                <button
                  className="button primary"
                  disabled={completion.isPending}
                  onClick={() => {
                    if (!completion.isPending)
                      completion.mutate(undefined, {
                        onSuccess: () => navigate(reportPath),
                      })
                  }}
                >
                  {completion.isPending ? '正在确认…' : '完成练习，查看报告'}
                </button>
              )}
            </div>
          )}
          <ErrorNotice error={completion.error} />
          <button
            type="button"
            className="text-button feedback-trigger"
            onClick={() => setFeedback(true)}
          >
            反馈题目问题
          </button>
        </section>
        <aside className="quiz-aside">
          <section className="card evidence-summary">
            <div className="card-heading">
              <span className="icon-tile mint">
                <BookOpen size={19} />
              </span>
              <h2>回到知识的出处</h2>
            </div>
            <p className="muted">理解答案，也理解它的依据。</p>
            <div className="evidence-placeholder">
              <FileText size={26} />
              <p>
                {quiz.source_status === 'legacy_unverified'
                  ? '历史题目未保存原始依据，无法核验出处。'
                  : quiz.source_status === 'model_only'
                    ? '这是一组通用知识练习，没有已保存的资料引用。'
                    : '选择已保存的引用，查看本题所依据的原文。'}
              </p>
            </div>
          </section>
          <section className="card question-map">
            <h2>练习进度</h2>
            <div>
              {quiz.questions.map((item, n) => (
                <button
                  key={item.id}
                  aria-label={`查看第 ${n + 1} 题`}
                  aria-current={n === index ? 'step' : undefined}
                  className={`${n === index ? 'current' : ''} ${(quiz.answer_records || []).some((answer) => answer.question_id === item.id) ? 'answered' : ''}`}
                  onClick={() => {
                    setIndex(n)
                    answerMutation.reset()
                  }}
                  disabled={answerMutation.isPending}
                >
                  {n + 1}
                </button>
              ))}
            </div>
            <p className="tiny muted">
              <span className="legend-square" />
              已提交
              <span className="legend-square current" />
              当前题目
            </p>
          </section>
          {quiz.images_status && quiz.images_status !== 'not_requested' && (
            <div className="source-note">
              <Image size={18} />
              <p>
                {['pending', 'queued', 'running', 'processing'].includes(quiz.images_status)
                  ? '配图仍在准备中，你可以先完成练习。'
                  : quiz.image_notice ||
                    (['failed', 'partial', 'partial_failed'].includes(quiz.images_status)
                      ? '部分配图未完成，不影响答题与报告。'
                      : '配图已处理完成。')}
              </p>
            </div>
          )}
          <div className="source-note">
            <CircleHelp size={18} />
            <p>判分与学习进度由服务端确认，刷新后可继续。</p>
          </div>
          {!!citations.length && (
            <section className="card citation-card">
              <h2>本题已保存的引用</h2>
              {citations.map((id, n) => (
                <button
                  type="button"
                  className="citation-button"
                  aria-label={`查看来源 ${n + 1}`}
                  key={id}
                  onClick={() => setEvidence(id)}
                >
                  <FileText size={17} />
                  <span>原文依据 {n + 1}</span>
                  <ArrowRight size={15} />
                </button>
              ))}
            </section>
          )}
        </aside>
      </div>
      {evidence && (
        <EvidencePanel quizId={quizId} evidenceId={evidence} onClose={() => setEvidence(null)} />
      )}
      {feedback && (
        <FeedbackForm
          key={question.id}
          quizId={quizId}
          questionId={question.id}
          onClose={() => setFeedback(false)}
        />
      )}
    </div>
  )
}
