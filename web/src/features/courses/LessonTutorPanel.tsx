import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CircleStop, FileText, MessageCircle, RefreshCw } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading, formatDate } from '../../components/ui'
import {
  courseErrorMessage,
  courseSourceRevoked,
  courseTaskErrorMessage,
  courseTaskPending,
} from '../../services/courses'
import { courseTutorKeys, readTutorEvidence } from '../../services/courseTutor'
import type { CourseLessonView, CourseTutorCreate } from '../../types/course'
import { locatorLabel } from '../evidence/EvidencePanel'
import type { LessonTutorController } from './useLessonTutor'

type AskMode = Exclude<NonNullable<CourseTutorCreate['mode']>, 'check'>
export type LessonTutorContext = { mode: AskMode; blockIndex: number | null }
const modeLabels = { explain: '讲解', example: '换个例子', hint: '给我提示', check: '检查理解' }

export function LessonTutorPanel({
  lesson,
  tutor,
  context,
  selectedTurnId,
  onClose,
  onUnavailable,
}: {
  lesson: CourseLessonView
  tutor: LessonTutorController
  context: LessonTutorContext
  selectedTurnId?: string
  onClose: () => void
  onUnavailable: () => void
}) {
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<AskMode>(context.mode)
  const [blockIndex, setBlockIndex] = useState<number | null>(context.blockIndex)
  const [evidence, setEvidence] = useState<{ turnId: string; sourceRef: string } | null>(null)
  const block = blockIndex === null ? null : lesson.blocks?.[blockIndex]
  useEffect(() => {
    if (selectedTurnId)
      document.getElementById(`tutor-turn-${selectedTurnId}`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedTurnId, tutor.turns.length])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (tutor.busy || (!question.trim() && blockIndex === null)) return
    const turn = await tutor.ask({
      expected_content_version: lesson.content_version,
      mode,
      block_index: blockIndex,
      question: question.trim(),
    })
    if (turn) setQuestion('')
  }
  return (
    <Dialog title="课内助教" className="course-tutor-dialog" onClose={onClose}>
      <p className="tiny muted">
        {lesson.title} · 回答和进度会保存在这一课。关闭面板后可接着阅读。
      </p>
      {tutor.query.error || tutor.inaccessible ? (
        <ErrorNotice
          error={courseErrorMessage(tutor.query.error || tutor.error || tutor.checksQuery.error)}
          onRetry={() => {
            void tutor.query.refetch()
          }}
        />
      ) : tutor.query.isPending ? (
        <Loading>正在恢复本课对话…</Loading>
      ) : (
        <div className="lesson-tutor-turns" aria-label="本课助教对话">
          {!tutor.turns.length && (
            <p className="muted">可以从正文某一段开始，也可以直接写下你的疑问。</p>
          )}
          {tutor.turns.map((turn) => (
            <section
              className="lesson-tutor-turn"
              id={`tutor-turn-${turn.turn_id}`}
              key={turn.turn_id}
            >
              <header className="section-line">
                <strong>
                  {modeLabels[turn.mode]}
                  {turn.block_index != null ? ` · 第 ${turn.block_index + 1} 段` : ''}
                </strong>
                <span className="tiny muted">{formatDate(turn.created_at)}</span>
              </header>
              {turn.question && <p className="lesson-tutor-question">{turn.question}</p>}
              {turn.mode === 'check' && (
                <p className="tiny muted">根据这次已保存的自检回答给出反馈，不计正式成绩。</p>
              )}
              {courseTaskPending(turn.task) ? (
                <div className="lesson-tutor-task" role="status">
                  <Loading>
                    {turn.task.status === 'pending'
                      ? '已排队，等待准备反馈…'
                      : '正在整理讲解与反馈…'}
                  </Loading>
                  <p className="tiny muted">可以关闭面板或离开页面，稍后回来继续查看。</p>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={tutor.pending !== null}
                    onClick={() => tutor.cancel(turn)}
                  >
                    <CircleStop size={16} />
                    {tutor.pending === 'cancel' ? '正在取消…' : '取消这次回答'}
                  </button>
                </div>
              ) : turn.task.status === 'completed' && turn.answer ? (
                <div className="lesson-tutor-answer">
                  <p>{turn.answer}</p>
                </div>
              ) : (
                <div className="lesson-tutor-task">
                  <p>
                    {turn.task.status === 'cancelled'
                      ? '这次回答已取消，之前的内容仍会保留。'
                      : courseTaskErrorMessage(turn.task)}
                  </p>
                  {['failed', 'cancelled'].includes(turn.task.status) && (
                    <button
                      type="button"
                      className="button secondary"
                      disabled={tutor.busy}
                      onClick={() => {
                        void tutor.retry(turn)
                      }}
                    >
                      <RefreshCw size={16} />
                      {tutor.pending === 'retry' ? '正在重试…' : '重试这次回答'}
                    </button>
                  )}
                </div>
              )}
              {!!turn.warnings?.length && (
                <div className="tiny muted">
                  {turn.warnings.map((warning, index) => (
                    <p key={index}>{warning}</p>
                  ))}
                </div>
              )}
              {turn.task.status === 'completed' && !!turn.sources?.length && (
                <div className="course-citations">
                  {turn.sources.map((source) => (
                    <button
                      type="button"
                      className="text-button"
                      key={source.source_ref}
                      onClick={() =>
                        setEvidence({ turnId: turn.turn_id, sourceRef: source.source_ref })
                      }
                    >
                      <FileText size={14} />
                      {source.title}
                      {source.locator ? ` · ${source.locator}` : ''}
                    </button>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
      <ErrorNotice error={tutor.error ? courseErrorMessage(tutor.error) : null} />
      <form
        className="stack-form lesson-tutor-composer"
        onSubmit={(event) => {
          void submit(event)
        }}
      >
        {block && (
          <div className="lesson-tutor-context">
            <div className="section-line">
              <strong>针对第 {blockIndex! + 1} 段</strong>
              <button type="button" className="text-button" onClick={() => setBlockIndex(null)}>
                改为整课提问
              </button>
            </div>
            <p>{block.text}</p>
          </div>
        )}
        <label>
          想怎样继续理解
          <select
            value={mode}
            disabled={tutor.busy}
            onChange={(event) => setMode(event.target.value as AskMode)}
          >
            <option value="explain">讲解这个问题</option>
            <option value="example">换个例子</option>
            <option value="hint">给我提示</option>
          </select>
        </label>
        <label>
          你的问题
          <textarea
            rows={3}
            maxLength={1000}
            value={question}
            disabled={tutor.pending !== null}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              block ? '可以补充你不理解的地方（选填）' : '写下这节课中想进一步理解的问题…'
            }
          />
        </label>
        <div className="button-row">
          <button
            type="submit"
            className="button primary"
            disabled={
              tutor.busy ||
              tutor.query.isPending ||
              !!tutor.query.error ||
              tutor.inaccessible ||
              (!question.trim() && blockIndex === null)
            }
          >
            <MessageCircle size={16} />
            {tutor.pending === 'ask'
              ? '正在提交…'
              : tutor.activeTurn
                ? '正在准备上一条回答'
                : '请助教帮助我'}
            <ArrowRight size={16} />
          </button>
          <button
            type="button"
            className="text-button"
            disabled={tutor.query.isFetching}
            onClick={() => {
              void tutor.query.refetch()
            }}
          >
            刷新对话
          </button>
        </div>
      </form>
      {evidence && !tutor.query.error && !tutor.inaccessible && (
        <TutorEvidence
          lesson={lesson}
          {...evidence}
          onClose={() => setEvidence(null)}
          onUnavailable={onUnavailable}
        />
      )}
    </Dialog>
  )
}

function TutorEvidence({
  lesson,
  turnId,
  sourceRef,
  onClose,
  onUnavailable,
}: {
  lesson: CourseLessonView
  turnId: string
  sourceRef: string
  onClose: () => void
  onUnavailable: () => void
}) {
  const identity = useIdentityKey()
  const query = useQuery({
    queryKey: courseTutorKeys.evidence(
      identity,
      lesson.course_id,
      lesson.lesson_id,
      turnId,
      sourceRef,
    ),
    queryFn: ({ signal }) =>
      readTutorEvidence(lesson.course_id, lesson.lesson_id, turnId, sourceRef, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
  })
  useEffect(() => {
    if (courseSourceRevoked(query.error)) onUnavailable()
  }, [query.error, onUnavailable])
  return (
    <Dialog title="这条回答的原文依据" className="evidence-panel" onClose={onClose}>
      {query.error ? (
        <ErrorNotice
          error={courseErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : query.isPending ? (
        <Loading>正在核对并读取原文…</Loading>
      ) : query.data ? (
        <>
          <div className="evidence-heading">
            <FileText size={20} />
            <div>
              <h3>{query.data.title}</h3>
              <span>{locatorLabel(query.data.locator)}</span>
            </div>
          </div>
          <div className="evidence-quote">
            <p style={{ whiteSpace: 'pre-wrap' }}>
              {query.data.excerpt || '此来源没有可展示的片段。'}
            </p>
          </div>
          <p className="evidence-footnote">本次助教回答实际使用的资料片段 · 已核对读取权限</p>
        </>
      ) : null}
    </Dialog>
  )
}
