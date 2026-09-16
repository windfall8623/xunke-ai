import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, List, MessageCircle, RefreshCw, Send } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { Dialog } from '../components/Dialog'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../components/ui'
import { AnswerCard } from '../features/qa/AnswerCard'
import { EvidenceDrawer } from '../features/qa/EvidenceDrawer'
import { ScopeForm } from '../features/qa/ScopeForm'
import { SessionList } from '../features/qa/SessionList'
import { TaskProgress, qaFailureLabel } from '../features/qa/TaskProgress'
import { activeTask, useQaSession } from '../features/qa/useQaSession'
import { PracticeFromAnswerDialog } from '../features/study/PracticeFromAnswerDialog'
import { qaApi, qaKeys } from '../services/qa'
import type { QaAnswer, QaMessage, QaSessionCreate } from '../types/qa'
import '../styles/qa.scss'

export function QaPage() {
  const { sessionId } = useParams()
  const [search] = useSearchParams()
  const [sessionsOpen, setSessionsOpen] = useState(false)
  useEffect(() => setSessionsOpen(false), [sessionId])
  return (
    <div className="qa-page">
      <PageHeading
        title="知识库问答"
        description="从资料中寻找答案，沿着引用核对原文。"
        action={
          <button
            className="button secondary qa-session-toggle"
            type="button"
            aria-expanded={sessionsOpen}
            aria-controls="qa-session-sidebar"
            onClick={() => setSessionsOpen((open) => !open)}
          >
            <List size={17} />
            {sessionsOpen ? '收起会话' : '会话列表'}
          </button>
        }
      />
      <div className="qa-layout">
        <aside
          id="qa-session-sidebar"
          aria-label="问答会话"
          className={`qa-session-sidebar ${sessionsOpen ? 'is-open' : ''}`}
        >
          <SessionList onChoose={() => setSessionsOpen(false)} />
        </aside>
        <div className="qa-main">
          {sessionId ? (
            <Conversation key={sessionId} sessionId={sessionId} />
          ) : (
            <NewSession key={search.get('doc_id') || 'new'} docId={search.get('doc_id')} />
          )}
        </div>
      </div>
    </div>
  )
}

function NewSession({ docId }: { docId: string | null }) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const navigate = useNavigate()
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const create = useMutation({
    mutationFn: (data: QaSessionCreate) => {
      const controller = new AbortController()
      request.current = controller
      return qaApi.createSession(data, controller.signal)
    },
    onSuccess: (session) => {
      if (request.current?.signal.aborted) return
      client.setQueryData(qaKeys.session(identity, session.session_id), session)
      void client.invalidateQueries({ queryKey: qaKeys.sessions(identity) })
      navigate(`/qa/${encodeURIComponent(session.session_id)}`)
    },
  })
  return (
    <section className="card qa-new-session">
      <div className="card-heading">
        <span className="icon-tile qa-new-session-icon">
          <MessageCircle size={23} />
        </span>
        <div>
          <h2>新建资料问答</h2>
          <p>先选择本次会话使用的资料与章节。</p>
        </div>
      </div>
      <ScopeForm
        initialDocId={docId}
        busy={create.isPending}
        error={create.error}
        onSubmit={(scope, title) => create.mutate({ scope, ...(title ? { title } : {}) })}
      />
    </section>
  )
}

function Conversation({ sessionId }: { sessionId: string }) {
  const qa = useQaSession(sessionId)
  const navigate = useNavigate()
  const [practiceAnswerId, setPracticeAnswerId] = useState<string | null>(null)
  const [scopeOpen, setScopeOpen] = useState(false)
  const [source, setSource] = useState<{ answerId: string; evidenceId: string } | null>(null)
  const { session, messages, task } = qa
  const practiceMessage = messages.find((message) => message.answer?.answer_id === practiceAnswerId)
  const practiceAnswer = practiceMessage
    ? practiceMessage.status === 'completed'
      ? practiceMessage.answer
      : null
    : task?.status === 'completed' && task.answer?.answer_id === practiceAnswerId
      ? task.answer
      : null
  function canPractice(answer: QaAnswer, status: QaMessage['status']) {
    return (
      !qa.hidden &&
      session?.source_status === 'active' &&
      status === 'completed' &&
      ['answered', 'partial'].includes(answer.answer_status) &&
      answer.blocks.some((block) => block.kind === 'fact' && !!block.citation_refs?.length)
    )
  }
  const practiceAllowed = !!practiceAnswer && canPractice(practiceAnswer, 'completed')
  useEffect(() => {
    if (!practiceAllowed) setPracticeAnswerId(null)
  }, [practiceAllowed])
  const taskInHistory =
    task &&
    messages.some(
      (message) =>
        message.role === 'assistant' &&
        message.task_id === task.task_id &&
        !['pending', 'running'].includes(message.status),
    )
  const sourceAllowed =
    source &&
    (messages.some(
      (message) => message.status !== 'revoked' && message.answer?.answer_id === source.answerId,
    ) ||
      (!taskInHistory && task?.answer?.answer_id === source.answerId))
  useEffect(() => {
    if (qa.hidden || !sourceAllowed) setSource(null)
  }, [qa.hidden, sourceAllowed])
  const lastQuestion = task
    ? messages.find((message) => message.task_id === task.task_id && message.role === 'user')
    : null
  const retryQuestion = lastQuestion?.content || qa.submittedQuestion?.data.content
  const retryRevision = lastQuestion?.scope_revision || qa.submittedQuestion?.data.scope_revision
  const canAsk = !!session && !qa.hidden && !qa.busy && !qa.uncertain && !qa.sessionQuery.error
  function submit(event: FormEvent) {
    event.preventDefault()
    qa.ask()
  }
  if (qa.sessionQuery.isPending)
    return (
      <section className="card">
        <Loading>正在恢复会话…</Loading>
      </section>
    )
  if (!session)
    return (
      <section className="card">
        <ErrorNotice
          error={qa.sessionQuery.error}
          onRetry={() => {
            void qa.refresh()
          }}
        />
      </section>
    )
  return (
    <section className="card qa-conversation">
      <header className="qa-conversation-heading">
        <div>
          <h2>{qa.hidden ? '资料已不可用' : session.title}</h2>
          <span className="muted tiny">范围版本 {session.scope_revision}</span>
        </div>
        <div className="qa-heading-actions">
          <button
            className="text-button"
            type="button"
            disabled={qa.busy || !!qa.uncertain}
            onClick={() => setScopeOpen(true)}
          >
            <FileText size={15} />
            更改范围
          </button>
          <button
            className="icon-button"
            type="button"
            aria-label="刷新会话"
            disabled={qa.sessionQuery.isFetching || qa.history.isFetching}
            onClick={() => {
              void qa.refresh()
            }}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </header>
      {!qa.hidden && (
        <div className="qa-scope-summary" aria-label="当前问答范围">
          {session.scope?.documents?.map((doc) => (
            <span key={doc.doc_id}>
              <FileText size={13} />
              {doc.title || '已选资料'} ·{' '}
              {doc.section_ids?.length ? `${doc.section_ids.length} 个章节` : '全文'}
            </span>
          ))}
        </div>
      )}
      <ErrorNotice error={qa.sessionQuery.error} />
      {qa.hidden ? (
        <div className="qa-revoked" role="alert">
          <FileText size={28} />
          <h3>资料授权或版本已不可用</h3>
          <p>相关问题、回答和引用已清除。更改范围后可以继续提问。</p>
        </div>
      ) : (
        <>
          {qa.history.hasNextPage && (
            <button
              className="text-button qa-load-history"
              type="button"
              disabled={qa.history.isFetchingNextPage}
              onClick={() => {
                void qa.history.fetchNextPage()
              }}
            >
              {qa.history.isFetchingNextPage ? '正在读取更早消息…' : '加载更早消息'}
            </button>
          )}
          <ErrorNotice
            error={qa.history.error}
            onRetry={() => {
              void qa.history.refetch()
            }}
          />
          {qa.history.isPending ? (
            <Loading>正在读取已保存的问答…</Loading>
          ) : (
            !messages.length &&
            !task &&
            !qa.submitting && (
              <EmptyState title="从一个问题开始">
                可以问概念、比较资料中的观点，也可以在回答后继续追问。
              </EmptyState>
            )
          )}
          <div
            className="qa-messages"
            role="log"
            aria-label="会话消息"
            aria-relevant="additions text"
          >
            {messages.map((message) => {
              if (
                message.role === 'assistant' &&
                ['pending', 'running'].includes(message.status) &&
                message.task_id === task?.task_id
              )
                return null
              const previousQuestion = messages.find(
                (item) =>
                  item.task_id === message.task_id &&
                  item.role === 'user' &&
                  item.status !== 'revoked',
              )
              return (
                <article
                  className={`qa-message qa-message-${message.role} ${message.status === 'revoked' ? 'qa-message-revoked' : ''}`}
                  key={message.message_id}
                >
                  <div className="qa-message-label">
                    {message.role === 'user' ? '你' : '资料回答'}
                    <span>范围 {message.scope_revision}</span>
                  </div>
                  {message.status === 'revoked' ? (
                    <p>资料已不可用，本轮内容不再展示。</p>
                  ) : message.role === 'user' ? (
                    <p>{message.content}</p>
                  ) : message.answer ? (
                    <AnswerCard
                      answer={message.answer}
                      onEvidence={(answerId, evidenceId) => setSource({ answerId, evidenceId })}
                      onUnavailable={qa.conceal}
                      onPractice={
                        canPractice(message.answer, message.status)
                          ? () => setPracticeAnswerId(message.answer!.answer_id)
                          : undefined
                      }
                    />
                  ) : message.status === 'failed' ? (
                    <div className="qa-task qa-task-failed">
                      <p role="status">{qaFailureLabel(message.error_code)}</p>
                      {previousQuestion &&
                        previousQuestion.scope_revision === session.scope_revision && (
                          <button
                            className="text-button"
                            type="button"
                            disabled={!canAsk}
                            onClick={() => qa.ask(previousQuestion.content)}
                          >
                            重试这个问题
                          </button>
                        )}
                    </div>
                  ) : message.status === 'cancelled' ? (
                    <p className="muted">已取消本次回答</p>
                  ) : (
                    <p className="muted">回答正在准备中，可刷新会话恢复进度。</p>
                  )}
                </article>
              )
            })}
            {qa.submittedQuestion &&
              task &&
              !messages.some(
                (message) => message.task_id === task.task_id && message.role === 'user',
              ) && (
                <article className="qa-message qa-message-user">
                  <div className="qa-message-label">
                    你<span>范围 {qa.submittedQuestion.data.scope_revision}</span>
                  </div>
                  <p>{qa.submittedQuestion.data.content}</p>
                </article>
              )}
            {task && !taskInHistory && (
              <article className="qa-message qa-message-assistant">
                <div className="qa-message-label">资料回答</div>
                {task.answer && task.status === 'completed' ? (
                  <AnswerCard
                    answer={task.answer}
                    onEvidence={(answerId, evidenceId) => setSource({ answerId, evidenceId })}
                    onUnavailable={qa.conceal}
                    onPractice={
                      canPractice(task.answer, 'completed')
                        ? () => setPracticeAnswerId(task.answer!.answer_id)
                        : undefined
                    }
                  />
                ) : (
                  <TaskProgress
                    task={task}
                    cancelling={qa.cancelling}
                    cancelError={qa.cancelError}
                    taskError={qa.taskQuery.error}
                    settling={qa.settling}
                    onCancel={() => {
                      void qa.cancel()
                    }}
                    onRefresh={() => {
                      void qa.taskQuery.refetch()
                    }}
                    onRetry={
                      retryQuestion && retryRevision === session.scope_revision && canAsk
                        ? () => qa.ask(retryQuestion)
                        : undefined
                    }
                  />
                )}
              </article>
            )}
          </div>
          {qa.taskQuery.error && !task && (
            <ErrorNotice
              error={qa.taskQuery.error}
              onRetry={() => {
                void qa.taskQuery.refetch()
              }}
            />
          )}
        </>
      )}
      <form className="qa-composer" onSubmit={submit}>
        <div className="qa-composer-heading">
          <label htmlFor="qa-question">你的问题</label>
          <span id="qa-question-help">回答中的引用可打开原文核对</span>
        </div>
        <textarea
          id="qa-question"
          aria-describedby="qa-question-help qa-question-count"
          rows={3}
          maxLength={2000}
          placeholder={
            activeTask(task) ? '当前回答完成后，可以继续追问。' : '根据这些资料，你想了解什么？'
          }
          value={qa.hidden ? '' : qa.question}
          disabled={!canAsk}
          onChange={(event) => qa.setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === 'Enter' &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing &&
              event.keyCode !== 229
            ) {
              event.preventDefault()
              qa.ask()
            }
          }}
        />
        {qa.uncertain && !qa.hidden && (
          <div className="notice qa-uncertain" role="alert">
            <p>提交结果尚未确认。重试会确认同一次提交，请勿重复新建问题。</p>
            <button
              className="text-button"
              type="button"
              disabled={qa.submitting}
              onClick={qa.retrySubmission}
            >
              重试确认提交
            </button>
          </div>
        )}
        <ErrorNotice error={qa.submitError} />
        <div className="qa-composer-footer">
          <span className="tiny muted" id="qa-question-count">
            {qa.hidden ? 0 : qa.question.length} / 2000{' '}
            <span className="qa-keyboard-hint">· Enter 发送，Shift+Enter 换行</span>
          </span>
          <button
            className="button primary"
            type="submit"
            disabled={!canAsk || !qa.question.trim()}
          >
            <Send size={16} />
            {qa.submitting ? '正在发送…' : '发送问题'}
          </button>
        </div>
      </form>
      {scopeOpen && (
        <Dialog
          title="更改问答范围"
          onClose={() => {
            if (!qa.scopeSaving) setScopeOpen(false)
          }}
        >
          <ScopeForm
            initialScope={session.scope}
            revision={session.scope_revision}
            busy={qa.busy || !!qa.uncertain}
            error={qa.scopeError}
            onSubmit={(scope) => {
              void qa.updateScope(scope).then((saved) => {
                if (saved) setScopeOpen(false)
              })
            }}
          />
        </Dialog>
      )}
      {source && sourceAllowed && !qa.hidden && (
        <EvidenceDrawer
          sessionId={sessionId}
          answerId={source.answerId}
          evidenceId={source.evidenceId}
          onClose={() => setSource(null)}
          onUnavailable={qa.conceal}
        />
      )}
      {practiceAnswer && practiceAllowed && (
        <PracticeFromAnswerDialog
          answer={practiceAnswer}
          messageStatus="completed"
          sourceStatus={session.source_status}
          onClose={() => setPracticeAnswerId(null)}
          onUnavailable={qa.conceal}
          onSubmitted={(created) => {
            setPracticeAnswerId(null)
            const returnTo = `/qa/${encodeURIComponent(sessionId)}`
            navigate(
              `/tasks/${encodeURIComponent(created.task_id)}?returnTo=${encodeURIComponent(returnTo)}`,
            )
          }}
        />
      )}
    </section>
  )
}
