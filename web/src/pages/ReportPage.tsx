import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Award,
  BookOpen,
  CheckCircle2,
  RefreshCw,
  Sparkles,
  Target,
} from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { ErrorNotice, Loading, StatusBadge } from '../components/ui'
import { api } from '../services/api'
import { providerErrorMessage } from '../services/providerErrors'
import { courseReturnPath, courseSummaryReturnPath, withCourseReturn } from '../services/courseNavigation'

export function ReportPage() {
  const { quizId = '' } = useParams()
  const identity = useIdentityKey()
  return <ReportWorkspace key={`${identity}:${quizId}`} quizId={quizId} identity={identity} />
}

function ReportWorkspace({ quizId, identity }: { quizId: string; identity: string | number }) {
  const [params] = useSearchParams()
  const key = useRef(crypto.randomUUID())
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const navigate = useNavigate()
  const report = useQuery({
    queryKey: [identity, 'report', quizId],
    queryFn: ({ signal }) => api.report(quizId, signal),
    refetchInterval: (state) =>
      ['pending', 'queued', 'running', 'processing'].includes(state.state.data?.report_status || '')
        ? 3500
        : false,
    refetchIntervalInBackground: false,
  })
  const quiz = useQuery({
    queryKey: [identity, 'quiz', quizId],
    queryFn: ({ signal }) => api.quiz(quizId, signal),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  const courseReturn = !quiz.error
    ? courseReturnPath(quiz.data?.course_context, params.get('returnTo'))
    : null
  const courseSummary = !quiz.error
    ? courseSummaryReturnPath(quiz.data?.course_context, params.get('returnTo')) : null
  const retry = useMutation({
    mutationFn: () => api.retryReport(quizId),
    onSuccess: () => {
      void report.refetch()
    },
  })
  const review = useMutation({
    mutationFn: () =>
      api.generate(
        { review_of_quiz_id: quizId, question_count: 3, difficulty: 'mixed' },
        key.current,
      ),
    onSuccess: (result) => {
      if (mounted.current) navigate(`/tasks/${encodeURIComponent(result.task_id)}`)
    },
  })
  if (quiz.error)
    return (
      <ErrorNotice
        error={quiz.error}
        onRetry={() => {
          void quiz.refetch()
        }}
      />
    )
  if (report.isPending) return <Loading>正在读取已确认的学习结果…</Loading>
  if (report.error || !report.data)
    return (
      <div className="report-page">
        <ErrorNotice
          error={report.error || '报告尚未就绪。请返回练习页核对保存结果。'}
          onRetry={() => { void report.refetch() }} />
        <Link className="button secondary" to={courseSummary || withCourseReturn(`/quizzes/${encodeURIComponent(quizId)}`, courseReturn)}>
          <ArrowLeft size={16} />{courseSummary ? '返回本课小结' : '回看练习记录'}
        </Link>
      </div>
    )
  const data = report.data
  const text = data.report
  const wrong = quiz.data?.answer_records?.filter((answer) => !answer.is_correct) || []
  const invalidSource = ['legacy_unverified', 'unavailable', 'source_revoked'].includes(
    quiz.data?.source_status || '',
  )
  return (
    <div className="report-page">
      <Link
        className="back-link"
        to={withCourseReturn(`/quizzes/${encodeURIComponent(quizId)}`, courseReturn)}
      >
        <ArrowLeft size={16} />
        回看练习
      </Link>
      {courseSummary && (
        <Link className="button secondary" to={courseSummary}>
          <BookOpen size={16} />
          返回本课小结
          <ArrowRight size={16} />
        </Link>
      )}
      <header className="report-hero">
        <div className="report-emblem">
          <Award size={36} />
        </div>
        <p className="eyebrow">每一次练习，都有新的发现</p>
        <h1>看见今天的进步</h1>
        <p className="muted">{quiz.data?.title || '本次学习报告'}</p>
        <div className="report-stats">
          <div>
            <strong>{Number(data.accuracy.toFixed(1))}%</strong>
            <span>正确率</span>
          </div>
          <div>
            <strong>
              {data.correct_count}
              <small> / {data.total_questions}</small>
            </strong>
            <span>正确作答</span>
          </div>
          <div>
            <strong className="xp-value">+{data.xp_awarded}</strong>
            <span>已确认经验值</span>
          </div>
        </div>
        <span className="verified-stats">
          <CheckCircle2 size={14} />
          统计已保存 · 重复查看不会重复结算
        </span>
      </header>
      <div className="report-grid">
        <section className="card report-analysis">
          <div className="card-heading">
            <span className="icon-tile indigo">
              <Sparkles size={20} />
            </span>
            <h2>这次学到了什么</h2>
            <StatusBadge status={data.report_status} />
          </div>
          {text ? (
            <>
              <div className="summary-lines">
                {text.three_line_summary?.map((line, i) => (
                  <p key={i}>
                    <span>{String(i + 1).padStart(2, '0')}</span>
                    {line}
                  </p>
                ))}
              </div>
              <div className="knowledge-groups">
                <div>
                  <h3>
                    <CheckCircle2 size={16} />
                    本次答对的知识点
                  </h3>
                  <div className="tag-list">
                    {text.mastered_points?.length ? (
                      text.mastered_points.map((point) => (
                        <span key={point} className="tag mint">
                          {point}
                        </span>
                      ))
                    ) : (
                      <p className="muted">继续练习，逐步巩固知识。</p>
                    )}
                  </div>
                </div>
                <div>
                  <h3>
                    <Target size={16} />
                    值得再练
                  </h3>
                  <div className="tag-list">
                    {text.weak_points?.length ? (
                      text.weak_points.map((point) => (
                        <a key={point} className="tag peach" href="#review-questions">
                          {point}
                        </a>
                      ))
                    ) : (
                      <p className="muted">这一组发挥不错。</p>
                    )}
                  </div>
                </div>
              </div>
              {!!text.advice?.length && (
                <div className="report-advice">
                  <h3>下一步建议</h3>
                  <ul>
                    {text.advice.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : data.report_status === 'failed' ? (
            <div className="analysis-pending">
              <Sparkles size={26} />
              <h3>学习分析暂未生成</h3>
              <p>{providerErrorMessage(data.error_code) || '文字分析暂时未能完成，请稍后重试。'}</p>
              <p>本次统计和已确认经验值仍然有效，可以单独重试文字分析。</p>
              <button
                className="button secondary"
                onClick={() => retry.mutate()}
                disabled={retry.isPending}
              >
                <RefreshCw size={16} />
                {retry.isPending ? '正在重试…' : '重试生成分析'}
              </button>
            </div>
          ) : (
            <div className="analysis-pending">
              <Loading>正在整理你的学习分析…</Loading>
              <p>已确认的统计可以先查看，分析完成后会自动更新。</p>
            </div>
          )}
          <ErrorNotice error={retry.error} />
        </section>
        <aside className="card next-step">
          <span className="icon-tile peach">
            <BookOpen size={22} />
          </span>
          <h2>
            把薄弱点，
            <br />
            变成下一次的进步。
          </h2>
          <p>
            {courseReturn
              ? '回到对应课时查看讲解与学习进度，也可针对本次错题再练 3 题。'
              : invalidSource
                ? '原始依据已失效或未核验。请明确选择新的资料再练习。'
                : '沿用这次的资料范围，为薄弱知识点再练 3 题。'}
          </p>
          {courseReturn ? (
            <Link className="button primary" to={`${courseReturn}#course-practice`}>
              回到本课继续学习
              <ArrowRight size={17} />
            </Link>
          ) : invalidSource ? (
            <Link className="button primary" to="/">
              重新选择资料
              <ArrowRight size={17} />
            </Link>
          ) : (
            <button
              className="button primary"
              disabled={!quiz.data || review.isPending}
              onClick={() => review.mutate()}
            >
              {review.isPending ? '正在准备…' : '再练一组'}
              <ArrowRight size={17} />
            </button>
          )}
          <ErrorNotice error={review.error} />
          <Link to="/me" className="text-link">
            查看全部学习记录
            <ArrowRight size={14} />
          </Link>
        </aside>
      </div>
      <section id="review-questions" className="card review-list">
        <div className="section-line">
          <h2>错题回顾</h2>
          <span className="muted tiny">与原题、已保存的引用一起复盘</span>
        </div>
        {wrong.length ? (
          wrong.map((answer) => {
            const question = quiz.data?.questions.find((item) => item.id === answer.question_id)
            return (
              <Link
                key={answer.question_id}
                to={withCourseReturn(
                  `/quizzes/${encodeURIComponent(quizId)}?question=${encodeURIComponent(answer.question_id)}`,
                  courseReturn,
                )}
                className="review-item"
              >
                <span className="icon-tile peach">
                  <Target size={18} />
                </span>
                <div>
                  <strong>{question?.stem || '查看这道题'}</strong>
                  <p>{question?.knowledge_point}</p>
                </div>
                <ArrowRight size={18} />
              </Link>
            )
          })
        ) : (
          <p className="muted">
            {quiz.isPending ? '正在读取作答记录…' : '本组没有错题，可回看全部练习巩固理解。'}
          </p>
        )}
      </section>
    </div>
  )
}
