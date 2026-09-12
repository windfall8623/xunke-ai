import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading } from '../../components/ui'
import {
  createStudySubmissionKeys,
  studyApi,
  studyConflict,
  studyErrorMessage,
  studyKeys,
  studyUnavailable,
  studyUncertain,
} from '../../services/study'
import type { Task } from '../../types/api'
import type { QaAnswer, QaMessage, QaSession } from '../../types/qa'
import type {
  StudyConceptList,
  StudyObjective,
  StudyQaPracticeContext,
  StudyQuizFromQa,
  StudySpace,
  StudySpaceList,
} from '../../types/study'
import { scopeCovers, StudyScopeSummary } from './StudyScopePicker'

type Props = {
  answer: QaAnswer
  messageStatus: QaMessage['status']
  sourceStatus: QaSession['source_status']
  onClose: () => void
  onSubmitted: (task: Task) => void
  onUnavailable?: () => void
}
type Operation = 'quiz' | 'space' | 'concept'
type Run = <T>(
  operation: Operation,
  work: (signal: AbortSignal) => Promise<T>,
  accept: (value: T) => void,
) => Promise<void>
const wrap = { minWidth: 0, overflowWrap: 'anywhere' as const }

export function PracticeFromAnswerDialog(props: Props) {
  const identity = useIdentityKey()
  const auth = useAuth()
  const eligible =
    auth.status === 'authenticated' &&
    props.messageStatus === 'completed' &&
    props.sourceStatus === 'active' &&
    ['answered', 'partial'].includes(props.answer.answer_status) &&
    props.answer.blocks.some((block) => block.kind === 'fact' && !!block.citation_refs?.length)
  return (
    <Dialog title="根据回答生成练习" onClose={props.onClose} className="wide-dialog">
      {eligible ? (
        <PracticeBody key={`${identity}:${props.answer.answer_id}`} {...props} />
      ) : (
        <p className="notice" role="status">
          {props.sourceStatus === 'revoked' || props.messageStatus === 'revoked'
            ? '资料已不可用，暂时不能根据此回答生成练习。'
            : '请等待回答完成，并确认回答中有可引用的事实后再生成练习。'}
        </p>
      )}
    </Dialog>
  )
}

function PracticeBody({ answer, onSubmitted, onUnavailable, onClose }: Props) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [hold, setHold] = useState<'conflict' | 'unavailable' | 'recheck' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uncertain, setUncertain] = useState<Operation | null>(null)
  const [pending, setPending] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [formRevision, setFormRevision] = useState(0)
  const inFlight = useRef(false)
  const active = useRef(true)
  const controller = useRef<AbortController | null>(null)
  const notified = useRef(false)
  const keyFor = useMemo(
    () => createStudySubmissionKeys(identity, answer.answer_id),
    [identity, answer.answer_id],
  )
  const context = useQuery({
    queryKey: studyKeys.practiceContext(identity, answer.answer_id),
    queryFn: ({ signal }) => studyApi.practiceContext(answer.answer_id, signal),
    enabled: !hold && !accepted,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  const spaces = useQuery({
    queryKey: studyKeys.spaces(identity, page, 'active'),
    queryFn: ({ signal }) => studyApi.spaces(page, 'active', signal),
    enabled: !hold && !accepted,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      controller.current?.abort()
    }
  }, [])
  const unavailable =
    hold === 'unavailable' || studyUnavailable(context.error) || studyUnavailable(spaces.error)
  useEffect(() => {
    if (!unavailable || notified.current) return
    notified.current = true
    controller.current?.abort()
    setHold('unavailable')
    client.removeQueries({ queryKey: studyKeys.practiceContext(identity, answer.answer_id) })
    onUnavailable?.()
  }, [unavailable, client, identity, answer.answer_id, onUnavailable])

  function issue(cause: unknown, operation?: Operation) {
    if (studyUnavailable(cause)) setHold('unavailable')
    else if (studyConflict(cause)) setHold('conflict')
    else if (studyUncertain(cause) && operation === 'concept') setHold('recheck')
    else {
      setError(studyErrorMessage(cause))
      setUncertain(studyUncertain(cause) ? operation || null : null)
    }
  }
  const run: Run = async (operation, work, accept) => {
    if (inFlight.current || hold || accepted) return
    inFlight.current = true
    setPending(true)
    setError(null)
    const current = new AbortController()
    controller.current = current
    try {
      const result = await work(current.signal)
      if (!active.current || current.signal.aborted) return
      setUncertain(null)
      accept(result)
    } catch (cause) {
      if (active.current && !current.signal.aborted) issue(cause, operation)
    } finally {
      inFlight.current = false
      if (active.current) setPending(false)
    }
  }
  async function recheck() {
    if (inFlight.current) return
    inFlight.current = true
    setPending(true)
    setError(null)
    try {
      await client.cancelQueries({ queryKey: studyKeys.all(identity) })
      const [nextContext, nextSpaces] = await Promise.all([context.refetch(), spaces.refetch()])
      if (!active.current) return
      if (nextContext.error || nextSpaces.error) {
        const cause = nextContext.error || nextSpaces.error
        if (studyUnavailable(cause)) setHold('unavailable')
        else setError(studyErrorMessage(cause))
        return
      }
      client.removeQueries({ queryKey: [identity, 'study', 'space'] })
      setFormRevision((value) => value + 1)
      setUncertain(null)
      setHold(null)
    } finally {
      inFlight.current = false
      if (active.current) setPending(false)
    }
  }
  if (unavailable)
    return (
      <p className="notice" role="alert">
        资料已不可用或访问权限已变更，回答内容与练习入口已隐藏。
      </p>
    )
  if (hold || studyConflict(context.error))
    return (
      <div className="stack-form" style={wrap}>
        <p className="notice" role="alert">
          {hold === 'recheck'
            ? '提交结果尚未确认，请重新核对已保存的概念后继续。'
            : '内容已更新，已清除旧选择。请重新核对回答和学习空间。'}
        </p>
        <ErrorNotice error={error} />
        <button
          type="button"
          className="button secondary"
          disabled={pending}
          onClick={() => {
            void recheck()
          }}
        >
          重新核对
        </button>
      </div>
    )
  if (accepted)
    return (
      <div className="stack-form">
        <p role="status">练习任务已提交，正在准备题目。</p>
        <button type="button" className="button secondary" onClick={onClose}>
          关闭
        </button>
      </div>
    )
  if (context.error || spaces.error)
    return (
      <ErrorNotice
        error="学习资料暂时无法读取，请重新核对后重试。"
        onRetry={() => {
          void recheck()
        }}
      />
    )
  if (!context.data || !spaces.data) return <Loading>正在核对回答与学习资料…</Loading>
  if (
    context.data.answer_id !== answer.answer_id ||
    context.data.session_id !== answer.session_id ||
    context.data.scope_revision !== answer.scope_revision ||
    context.data.answer_status !== answer.answer_status
  ) {
    return (
      <p className="notice" role="alert">
        回答信息已变化，请关闭后重新进入练习。
      </p>
    )
  }
  const contextIdentity = JSON.stringify(context.data)
  return (
    <PracticeFields
      key={`${formRevision}:${contextIdentity}`}
      context={context.data}
      spaces={spaces.data}
      page={page}
      setPage={setPage}
      pending={pending}
      uncertain={uncertain}
      error={error}
      run={run}
      keyFor={keyFor}
      onIssue={issue}
      onSubmitted={(task) => {
        setAccepted(true)
        onSubmitted(task)
      }}
    />
  )
}

function PracticeFields({
  context,
  spaces,
  page,
  setPage,
  pending,
  uncertain,
  error,
  run,
  keyFor,
  onIssue,
  onSubmitted,
}: {
  context: StudyQaPracticeContext
  spaces: StudySpaceList
  page: number
  setPage: (value: number) => void
  pending: boolean
  uncertain: Operation | null
  error: string | null
  run: Run
  keyFor: ReturnType<typeof createStudySubmissionKeys>
  onIssue: (cause: unknown) => void
  onSubmitted: (task: Task) => void
}) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const facts = context.fact_blocks.filter(
    (block) => block.kind === 'fact' && !!block.citation_refs?.length,
  )
  const [spaceId, setSpaceId] = useState('')
  const [scopeRevision, setScopeRevision] = useState(0)
  const [objectives, setObjectives] = useState<StudyObjective[]>([])
  const [blockIds, setBlockIds] = useState<string[]>(
    context.answer_status === 'answered' ? facts.map((block) => block.block_id) : [],
  )
  const [questionCount, setQuestionCount] = useState('5')
  const [difficulty, setDifficulty] = useState<StudyQuizFromQa['difficulty']>('mixed')
  const [creatingSpace, setCreatingSpace] = useState(false)
  const [spaceTitle, setSpaceTitle] = useState('')
  const [newConcept, setNewConcept] = useState('')
  const selectedSpace = useQuery({
    queryKey: studyKeys.space(identity, spaceId),
    queryFn: ({ signal }) => studyApi.space(spaceId, signal),
    enabled: !!spaceId,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const scope = useQuery({
    queryKey: studyKeys.scope(identity, spaceId, scopeRevision),
    queryFn: ({ signal }) => studyApi.scope(spaceId, scopeRevision, signal),
    enabled: !!spaceId && scopeRevision > 0,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const concepts = useQuery({
    queryKey: studyKeys.concepts(identity, spaceId),
    queryFn: ({ signal }) => studyApi.concepts(spaceId, signal),
    enabled: !!spaceId,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const queryError = selectedSpace.error || scope.error || concepts.error
  const revoked = selectedSpace.data?.source_status === 'revoked'
  useEffect(() => {
    if (queryError && (studyUnavailable(queryError) || studyConflict(queryError)))
      onIssue(queryError)
  }, [queryError, onIssue])
  useEffect(() => {
    if (!revoked) return
    setObjectives([])
    setNewConcept('')
  }, [revoked])
  const availableConcepts = (concepts.data?.items || []).filter(
    (item) => item.space_id === spaceId && item.source_status === 'active',
  )
  const compatible =
    !!spaceId &&
    !queryError &&
    selectedSpace.data?.status === 'active' &&
    !revoked &&
    scope.data?.space_id === spaceId &&
    scope.data.scope_revision === scopeRevision &&
    scopeCovers(scope.data.scope, context.scope)
  const validObjectives =
    objectives.length > 0 &&
    objectives.length <= 3 &&
    objectives.every(
      (objective) =>
        !!objective.title.trim() &&
        objective.title.trim().length <= 500 &&
        availableConcepts.some((item) => item.concept_id === objective.concept_id),
    )
  const validCount =
    Number.isInteger(Number(questionCount)) &&
    Number(questionCount) >= 3 &&
    Number(questionCount) <= 10
  const canSubmit =
    compatible &&
    validObjectives &&
    validCount &&
    blockIds.length > 0 &&
    blockIds.every((id) => facts.some((block) => block.block_id === id))
  function selectSpace(next: StudySpace) {
    setSpaceId(next.space_id)
    setScopeRevision(next.scope_revision)
    setObjectives([])
    setNewConcept('')
    setCreatingSpace(false)
  }
  function createSpace(event: FormEvent) {
    event.preventDefault()
    if (!spaceTitle.trim() || spaceTitle.trim().length > 80 || pending) return
    const data = {
      title: spaceTitle.trim(),
      timezone: 'Asia/Shanghai',
      answer_id: context.answer_id,
    }
    void run(
      'space',
      async (signal) =>
        studyApi.createSpace(data, await keyFor('space', JSON.stringify(data)), signal),
      (next) => {
        keyFor.settle('space', JSON.stringify(data))
        client.setQueryData(studyKeys.space(identity, next.space_id), next)
        client.setQueryData<StudySpaceList>(
          studyKeys.spaces(identity, page, 'active'),
          (current) =>
            current
              ? {
                  ...current,
                  items: [next, ...current.items.filter((item) => item.space_id !== next.space_id)],
                  total: current.total + 1,
                }
              : current,
        )
        selectSpace(next)
      },
    )
  }
  function addConcept(event: FormEvent) {
    event.preventDefault()
    if (!compatible || !newConcept.trim() || newConcept.trim().length > 80 || pending) return
    void run(
      'concept',
      (signal) =>
        studyApi.createConcept(
          spaceId,
          { title: newConcept.trim(), scope_revision: scopeRevision },
          signal,
        ),
      (next) => {
        client.setQueryData<StudyConceptList>(studyKeys.concepts(identity, spaceId), (current) => ({
          items: [
            ...(current?.items || []).filter((item) => item.concept_id !== next.concept_id),
            next,
          ],
        }))
        setNewConcept('')
      },
    )
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (pending || !canSubmit) return
    const data: StudyQuizFromQa = {
      answer_id: context.answer_id,
      space_id: spaceId,
      scope_revision: scopeRevision,
      block_ids: [...blockIds].sort(),
      objectives: objectives.map((objective) => ({ ...objective, title: objective.title.trim() })),
      question_count: Number(questionCount),
      difficulty,
    }
    void run(
      'quiz',
      async (signal) =>
        studyApi.quizFromQa(data, await keyFor('quiz', JSON.stringify(data)), signal),
      (task) => {
        keyFor.settle('quiz', JSON.stringify(data))
        onSubmitted(task)
      },
    )
  }
  const selected = selectedSpace.data || spaces.items.find((item) => item.space_id === spaceId)
  const spaceChoices =
    selected && !spaces.items.some((item) => item.space_id === selected.space_id)
      ? [selected, ...spaces.items]
      : spaces.items
  return (
    <div className="stack-form" style={wrap}>
      <p className="muted">
        选择学习空间与练习目标。循课将依据本次回答保存的资料生成单选、多选和判断题。
      </p>
      <StudyScopeSummary scope={context.scope} revision={context.scope_revision} />
      <fieldset className="stack-form" disabled={pending}>
        <label>
          学习空间
          <select
            value={spaceId}
            onChange={(event) => {
              const next = spaceChoices.find((item) => item.space_id === event.target.value)
              if (next) selectSpace(next)
              else {
                setSpaceId('')
                setScopeRevision(0)
                setObjectives([])
                setNewConcept('')
              }
            }}
          >
            <option value="">请选择学习空间</option>
            {spaceChoices.map((item) => (
              <option
                value={item.space_id}
                key={item.space_id}
                disabled={item.source_status === 'revoked' || item.status === 'archived'}
              >
                {item.source_status === 'revoked' ? '资料已失效的学习空间' : item.title}
              </option>
            ))}
          </select>
        </label>
        {spaces.total > spaces.page_size && (
          <div className="button-row" aria-label="学习空间分页">
            <button
              type="button"
              className="button secondary"
              disabled={pending || page <= 1}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </button>
            <span>第 {page} 页</span>
            <button
              type="button"
              className="button secondary"
              disabled={pending || page * spaces.page_size >= spaces.total}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </button>
          </div>
        )}
        <button
          type="button"
          className="button secondary"
          onClick={() => setCreatingSpace((value) => !value)}
        >
          新建学习空间
        </button>
      </fieldset>
      {creatingSpace && (
        <form className="stack-form" aria-label="新建学习空间" onSubmit={createSpace}>
          <label>
            空间名称
            <input
              value={spaceTitle}
              required
              maxLength={80}
              disabled={pending}
              onChange={(event) => setSpaceTitle(event.target.value)}
            />
          </label>
          <p className="muted tiny">新空间保留本次回答的资料快照，学习时间按北京时间安排。</p>
          <button type="submit" className="button primary" disabled={pending || !spaceTitle.trim()}>
            {pending ? '正在提交…' : '创建并选择空间'}
          </button>
        </form>
      )}
      {!!spaceId && (
        <fieldset className="stack-form" disabled={pending}>
          <label>
            固定范围版本
            <select
              value={scopeRevision}
              onChange={(event) => {
                setScopeRevision(Number(event.target.value))
                setObjectives([])
                setNewConcept('')
              }}
            >
              {Array.from(
                { length: selected?.scope_revision || scopeRevision },
                (_, index) => index + 1,
              ).map((revision) => (
                <option value={revision} key={revision}>
                  范围版本 {revision}
                </option>
              ))}
            </select>
          </label>
          {selectedSpace.isPending || scope.isPending ? <Loading>正在核对固定来源…</Loading> : null}
          {revoked ? (
            <p className="notice" role="alert">
              资料已不可用，请重新选择学习空间。
            </p>
          ) : selectedSpace.data?.status === 'archived' ? (
            <p className="notice" role="alert">
              此空间已归档，请选择其他空间或先恢复空间。
            </p>
          ) : scope.data && !compatible && !queryError ? (
            <p className="notice" role="alert">
              所选范围未覆盖回答的完整来源版本，请选择兼容的范围或从本次回答新建空间。
            </p>
          ) : null}
          {queryError && <ErrorNotice error="学习空间暂时无法读取，请重新选择后重试。" />}
          {compatible && scope.data && (
            <StudyScopeSummary scope={scope.data.scope} revision={scopeRevision} />
          )}
        </fieldset>
      )}
      {compatible && (
        <form className="stack-form" aria-label="新增练习概念" onSubmit={addConcept}>
          <label>
            新概念名称
            <input
              maxLength={80}
              value={newConcept}
              disabled={pending}
              onChange={(event) => setNewConcept(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="button secondary"
            disabled={pending || !newConcept.trim()}
          >
            添加概念
          </button>
        </form>
      )}
      <form className="stack-form" aria-label="根据回答生成练习" onSubmit={submit}>
        <fieldset className="stack-form" disabled={pending}>
          <fieldset className="stack-form" disabled={pending || !compatible}>
            <legend>练习概念与目标（最多 3 个）</legend>
            {spaceId && concepts.isPending ? <Loading>正在读取学习概念…</Loading> : null}
            {compatible && !availableConcepts.length && (
              <p className="muted">还没有可用概念，请先添加一个明确的学习概念。</p>
            )}
            {availableConcepts.map((item) => {
              const objective = objectives.find((entry) => entry.concept_id === item.concept_id)
              return (
                <div className="stack-form" key={item.concept_id} style={wrap}>
                  <label
                    className="checkbox-row"
                    style={{ display: 'flex', alignItems: 'flex-start' }}
                  >
                    <input
                      type="checkbox"
                      aria-label={`练习概念：${item.title}`}
                      checked={!!objective}
                      disabled={pending || !compatible || (!objective && objectives.length >= 3)}
                      onChange={(event) => {
                        setObjectives(
                          event.target.checked
                            ? [
                                ...objectives,
                                { concept_id: item.concept_id, title: context.retrieval_query },
                              ]
                            : objectives.filter((entry) => entry.concept_id !== item.concept_id),
                        )
                      }}
                    />
                    <span style={wrap}>{item.title}</span>
                  </label>
                  {objective && (
                    <label>
                      练习目标：{item.title}
                      <textarea
                        rows={3}
                        maxLength={500}
                        value={objective.title}
                        onChange={(event) =>
                          setObjectives(
                            objectives.map((entry) =>
                              entry.concept_id === item.concept_id
                                ? { ...entry, title: event.target.value }
                                : entry,
                            ),
                          )
                        }
                      />
                    </label>
                  )}
                  {objective && objective.title.length > 500 && (
                    <p className="notice">原问题较长，请将练习目标精简至 500 字以内。</p>
                  )}
                </div>
              )
            })}
          </fieldset>
          <fieldset className="stack-form" disabled={pending}>
            <legend>作为练习依据的事实</legend>
            {context.answer_status === 'partial' && (
              <p className="notice">此回答仅部分有依据，请主动勾选希望练习的事实。</p>
            )}
            {facts.map((block) => (
              <label
                className="checkbox-row"
                key={block.block_id}
                style={{ display: 'flex', alignItems: 'flex-start' }}
              >
                <input
                  type="checkbox"
                  checked={blockIds.includes(block.block_id)}
                  onChange={(event) =>
                    setBlockIds(
                      event.target.checked
                        ? [...blockIds, block.block_id]
                        : blockIds.filter((id) => id !== block.block_id),
                    )
                  }
                />
                <span style={wrap}>{block.text}</span>
              </label>
            ))}
            {!facts.length && <p className="notice">此回答暂无可用于练习的引用事实。</p>}
          </fieldset>
          <div className="rubric-fields">
            <label>
              题目数量
              <input
                type="number"
                min={3}
                max={10}
                step={1}
                value={questionCount}
                onChange={(event) => setQuestionCount(event.target.value)}
              />
            </label>
            <label>
              练习难度
              <select
                value={difficulty}
                onChange={(event) =>
                  setDifficulty(event.target.value as StudyQuizFromQa['difficulty'])
                }
              >
                <option value="mixed">综合难度</option>
                <option value="easy">基础</option>
                <option value="medium">进阶</option>
                <option value="hard">挑战</option>
              </select>
            </label>
          </div>
          <ErrorNotice error={error} />
          <button type="submit" className="button primary" disabled={pending || !canSubmit}>
            {pending ? '正在提交…' : uncertain === 'quiz' ? '重试生成练习' : '生成练习'}
          </button>
        </fieldset>
      </form>
    </div>
  )
}
