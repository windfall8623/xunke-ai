import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { GoalEditor, studyPlanLabels } from '../../features/study/GoalEditor'
import { StudyScopePicker, StudyScopeSummary } from '../../features/study/StudyScopePicker'
import { GeneratePracticeDialog } from '../../features/practice/GeneratePracticeDialog'
import {
  studyApi,
  studyConflict,
  studyErrorMessage,
  studyKeys,
  studyUnavailable,
  studyUncertain,
} from '../../services/study'
import type { SourceScope } from '../../types/api'
import type {
  StudyConcept,
  StudyConceptList,
  StudyGoal,
  StudyGoalCreate,
  StudyGoalList,
  StudyScope,
  StudySpace,
  StudySpaceUpdate,
  StudyUnit,
  StudyUnitCreate,
  StudyUnitList,
} from '../../types/study'

const wrap = { minWidth: 0, overflowWrap: 'anywhere' as const }
const queryOptions = { staleTime: 0, gcTime: 0, retry: false, refetchOnMount: 'always' as const }

/** Source-bound space settings and learning goals. */
export function StudySpacePage({ spaceId: suppliedId }: { spaceId?: string } = {}) {
  const params = useParams<{ spaceId: string }>()
  const spaceId = suppliedId || params.spaceId
  const identity = useIdentityKey()
  const auth = useAuth()
  if (auth.status !== 'authenticated') return <p className="notice">请先登录后查看学习空间。</p>
  if (!spaceId)
    return (
      <EmptyState title="请选择学习空间">打开一个已保存的学习空间后即可查看目标与单元。</EmptyState>
    )
  return <SpaceLoader key={`${identity}:${spaceId}`} spaceId={spaceId} />
}

function SpaceLoader({ spaceId }: { spaceId: string }) {
  const identity = useIdentityKey()
  const space = useQuery({
    queryKey: studyKeys.space(identity, spaceId),
    queryFn: ({ signal }) => studyApi.space(spaceId, signal),
    ...queryOptions,
  })
  if (space.error)
    return (
      <ErrorNotice
        error={
          studyUnavailable(space.error)
            ? studyErrorMessage(space.error)
            : '学习空间暂时无法读取，请重新加载。'
        }
        onRetry={() => {
          void space.refetch()
        }}
      />
    )
  if (!space.data) return <Loading>正在读取学习空间…</Loading>
  if (space.data.source_status === 'revoked' || !space.data.scope)
    return (
      <div style={wrap}>
        <PageHeading eyebrow="循课 · 学习空间" title="资料已失效的学习空间" />
        <p className="notice" role="alert">
          资料已不可用或访问权限已变更，相关目标、概念和学习单元已隐藏。
        </p>
        <button
          type="button"
          className="button secondary"
          onClick={() => {
            void space.refetch()
          }}
        >
          重新加载
        </button>
      </div>
    )
  return <SpaceContent space={space.data} />
}

function SpaceContent({ space }: { space: StudySpace }) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [scopeRevision, setScopeRevision] = useState(space.scope_revision)
  const [editingConcept, setEditingConcept] = useState<StudyConcept | null>(null)
  const [showConcept, setShowConcept] = useState(false)
  const [showPractice, setShowPractice] = useState(false)
  const [editingGoal, setEditingGoal] = useState<StudyGoal | null>(null)
  const [showGoal, setShowGoal] = useState(false)
  const [selectedGoal, setSelectedGoal] = useState<StudyGoal | null>(null)
  const [editingUnit, setEditingUnit] = useState<StudyUnit | null>(null)
  const [showUnit, setShowUnit] = useState(false)
  const [showScope, setShowScope] = useState(false)
  const [scopeBaseRevision, setScopeBaseRevision] = useState(space.revision)
  const [nextScope, setNextScope] = useState<SourceScope | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hold, setHold] = useState<string | null>(null)
  const [settingsVersion, setSettingsVersion] = useState(0)
  const inFlight = useRef(false)
  const alive = useRef(true)
  const controller = useRef<AbortController | null>(null)
  const archived = space.status === 'archived'
  const scope = useQuery({
    queryKey: studyKeys.scope(identity, space.space_id, scopeRevision),
    queryFn: ({ signal }) => studyApi.scope(space.space_id, scopeRevision, signal),
    ...queryOptions,
  })
  const concepts = useQuery({
    queryKey: studyKeys.concepts(identity, space.space_id),
    queryFn: ({ signal }) => studyApi.concepts(space.space_id, signal),
    ...queryOptions,
  })
  const goals = useQuery({
    queryKey: studyKeys.goals(identity, space.space_id),
    queryFn: ({ signal }) => studyApi.goals(space.space_id, signal),
    ...queryOptions,
  })
  const units = useQuery({
    queryKey: studyKeys.units(identity, space.space_id, selectedGoal?.goal_id || ''),
    queryFn: ({ signal }) => studyApi.units(selectedGoal!.goal_id, signal),
    enabled: !!selectedGoal,
    ...queryOptions,
  })
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      controller.current?.abort()
    }
  }, [])
  const revokedSelection = !!(
    (editingConcept &&
      concepts.data &&
      concepts.data.items.find((item) => item.concept_id === editingConcept.concept_id)
        ?.source_status !== 'active') ||
    (editingGoal &&
      goals.data &&
      goals.data.items.find((item) => item.goal_id === editingGoal.goal_id)?.source_status !==
        'active') ||
    (selectedGoal &&
      goals.data &&
      goals.data.items.find((item) => item.goal_id === selectedGoal.goal_id)?.source_status !==
        'active') ||
    (editingUnit &&
      units.data &&
      units.data.items.find((item) => item.unit_id === editingUnit.unit_id)?.source_status !==
        'active')
  )
  useEffect(() => {
    if (!revokedSelection) return
    controller.current?.abort()
    setEditingConcept(null)
    setShowConcept(false)
    setEditingGoal(null)
    setShowGoal(false)
    setEditingUnit(null)
    setShowUnit(false)
    setSelectedGoal(null)
    setHold('资料已不可用或访问权限已变更，正在编辑的学习内容已隐藏。')
  }, [revokedSelection])
  function resetEditors() {
    setEditingConcept(null)
    setShowConcept(false)
    setEditingGoal(null)
    setShowGoal(false)
    setEditingUnit(null)
    setShowUnit(false)
    setSelectedGoal(null)
    setNextScope(null)
    setShowScope(false)
  }
  async function run<T>(work: (signal: AbortSignal) => Promise<T>, accept: (value: T) => void) {
    if (inFlight.current || hold) return
    inFlight.current = true
    setPending(true)
    setError(null)
    const current = new AbortController()
    controller.current = current
    try {
      const result = await work(current.signal)
      if (!alive.current || current.signal.aborted) return
      accept(result)
      await client.invalidateQueries({ queryKey: studyKeys.space(identity, space.space_id) })
      await client.invalidateQueries({ queryKey: [identity, 'study', 'spaces'] })
    } catch (cause) {
      if (!alive.current || current.signal.aborted) return
      if (studyUnavailable(cause) || studyConflict(cause)) {
        resetEditors()
        setHold(studyErrorMessage(cause))
      } else if (studyUncertain(cause)) {
        resetEditors()
        setHold('提交结果尚未确认。请先重新加载，核对已保存的内容后再继续，避免重复添加。')
      } else setError(studyErrorMessage(cause))
    } finally {
      inFlight.current = false
      if (alive.current) setPending(false)
    }
  }
  async function reload() {
    if (pending) return
    setPending(true)
    await client.resetQueries({ queryKey: studyKeys.space(identity, space.space_id) })
    if (alive.current) {
      resetEditors()
      setHold(null)
      setError(null)
      setSettingsVersion((value) => value + 1)
      setPending(false)
    }
  }
  const readError = scope.error || concepts.error || goals.error || units.error
  if (hold || readError || revokedSelection)
    return (
      <div className="stack-form" style={wrap}>
        <p className="notice" role="alert">
          {hold ||
            (revokedSelection
              ? '资料已不可用，正在编辑的学习内容已隐藏。'
              : studyUnavailable(readError)
                ? studyErrorMessage(readError)
                : '学习内容暂时无法读取，请重新加载后继续。')}
        </p>
        <button
          className="button secondary"
          type="button"
          disabled={pending}
          onClick={() => {
            void reload()
          }}
        >
          重新加载
        </button>
      </div>
    )
  function saveGoal(data: StudyGoalCreate) {
    if (archived) return
    const existing = editingGoal
    void run(
      (signal) =>
        existing
          ? studyApi.updateGoal(
              existing.goal_id,
              {
                expected_revision: existing.revision,
                title: data.title,
                deadline: data.deadline,
                daily_minutes: data.daily_minutes,
                status: data.status,
              },
              signal,
            )
          : studyApi.createGoal(space.space_id, data, signal),
      (next) => {
        client.setQueryData<StudyGoalList>(
          studyKeys.goals(identity, space.space_id),
          (current) => ({
            items: [
              ...(current?.items || []).filter((item) => item.goal_id !== next.goal_id),
              next,
            ],
          }),
        )
        setEditingGoal(null)
        setShowGoal(false)
      },
    )
  }
  function saveConcept(title: string) {
    if (archived) return
    const existing = editingConcept
    void run(
      (signal) =>
        existing
          ? studyApi.updateConcept(
              existing.concept_id,
              {
                title,
                expected_revision: existing.revision,
                scope_revision: existing.scope_revision,
              },
              signal,
            )
          : studyApi.createConcept(
              space.space_id,
              { title, scope_revision: scopeRevision },
              signal,
            ),
      (next) => {
        client.setQueryData<StudyConceptList>(
          studyKeys.concepts(identity, space.space_id),
          (current) => ({
            items: [
              ...(current?.items || []).filter((item) => item.concept_id !== next.concept_id),
              next,
            ],
          }),
        )
        setEditingConcept(null)
        setShowConcept(false)
      },
    )
  }
  function saveUnit(data: StudyUnitCreate) {
    if (archived || !selectedGoal || !units.data) return
    const existing = editingUnit
    void run(
      (signal) =>
        existing
          ? studyApi.updateUnit(
              existing.unit_id,
              { expected_revision: existing.revision, title: data.title, status: data.status },
              signal,
            )
          : studyApi.createUnit(selectedGoal.goal_id, data, signal),
      () => {
        setEditingUnit(null)
        setShowUnit(false)
      },
    )
  }
  function moveUnit(unitId: string, offset: -1 | 1) {
    if (
      archived ||
      !selectedGoal ||
      !units.data ||
      units.data.items.some((item) => item.source_status === 'revoked')
    )
      return
    const ordered = units.data.items.map((item) => item.unit_id)
    const index = ordered.indexOf(unitId)
    if (index < 0 || index + offset < 0 || index + offset >= ordered.length) return
    ;[ordered[index], ordered[index + offset]] = [ordered[index + offset], ordered[index]]
    void run(
      (signal) =>
        studyApi.reorderUnits(
          selectedGoal.goal_id,
          { expected_revision: units.data.goal_revision, unit_ids: ordered },
          signal,
        ),
      (next) => {
        client.setQueryData<StudyUnitList>(
          studyKeys.units(identity, space.space_id, selectedGoal.goal_id),
          next,
        )
      },
    )
  }
  const scoped =
    scope.data?.space_id === space.space_id && scope.data.scope_revision === scopeRevision
      ? scope.data.scope
      : undefined
  return (
    <div className="stack-form" style={wrap}>
      <PageHeading
        eyebrow="循课 · 学习空间"
        title={space.title}
        description="明确目标，按固定资料安排学习单元。"
      />
      <div className="button-row">
        <button
          className="button primary"
          disabled={
            archived || !scoped || !!scope.error || !!concepts.error || !concepts.data?.items.length
          }
          onClick={() => setShowPractice(true)}
        >
          生成综合练习
        </button>
        <Link
          className="button secondary"
          to={`/study/reviews?space_id=${encodeURIComponent(space.space_id)}`}
        >
          复习安排
        </Link>
        <Link
          className="button secondary"
          to={`/study/wrong-questions?space_id=${encodeURIComponent(space.space_id)}`}
        >
          本空间错题
        </Link>
        <Link
          className="button secondary"
          to={`/study/history?space_id=${encodeURIComponent(space.space_id)}`}
        >
          学习历史
        </Link>
      </div>
      {showPractice && !archived && scoped && !scope.error && !concepts.error && (
        <GeneratePracticeDialog
          key={scopeRevision}
          space={space}
          concepts={concepts.data?.items || []}
          scopeRevision={scopeRevision}
          onClose={() => setShowPractice(false)}
        />
      )}
      {archived ? (
        <section className="card stack-form" style={wrap}>
          <p className="notice" role="status">
            此学习空间已归档，当前为只读状态。
          </p>
          <button
            className="button secondary"
            type="button"
            disabled={pending}
            onClick={() => {
              void run(
                (signal) =>
                  studyApi.updateSpace(
                    space.space_id,
                    { expected_revision: space.revision, status: 'active' },
                    signal,
                  ),
                (next) => client.setQueryData(studyKeys.space(identity, space.space_id), next),
              )
            }}
          >
            恢复空间
          </button>
        </section>
      ) : (
        <section className="card stack-form" style={wrap}>
          <SpaceSettings
            key={`${space.space_id}:${settingsVersion}`}
            space={space}
            disabled={pending}
            onReload={() => {
              void reload()
            }}
            onSubmit={(data) => {
              void run(
                (signal) => studyApi.updateSpace(space.space_id, data, signal),
                (next) => {
                  client.setQueryData(studyKeys.space(identity, space.space_id), next)
                  setSettingsVersion((value) => value + 1)
                },
              )
            }}
          />
          <button
            className="text-button"
            type="button"
            disabled={pending}
            onClick={() => {
              void run(
                (signal) =>
                  studyApi.updateSpace(
                    space.space_id,
                    { expected_revision: space.revision, status: 'archived' },
                    signal,
                  ),
                (next) => {
                  resetEditors()
                  client.setQueryData(studyKeys.space(identity, space.space_id), next)
                },
              )
            }}
          >
            归档空间
          </button>
        </section>
      )}
      <ErrorNotice error={error} />
      <section className="card stack-form" aria-label="学习范围" style={wrap}>
        <h2>学习范围</h2>
        <label>
          固定范围版本
          <select
            disabled={pending}
            value={scopeRevision}
            onChange={(event) => {
              setScopeRevision(Number(event.target.value))
              resetEditors()
            }}
          >
            {Array.from({ length: space.scope_revision }, (_, index) => index + 1).map(
              (revision) => (
                <option value={revision} key={revision}>
                  范围版本 {revision}
                </option>
              ),
            )}
          </select>
        </label>
        {scope.isPending ? (
          <Loading>正在读取固定资料…</Loading>
        ) : (
          scoped && <StudyScopeSummary scope={scoped} revision={scopeRevision} />
        )}
        {!archived && (
          <button
            type="button"
            className="button secondary"
            disabled={pending}
            onClick={() => {
              setShowScope((value) => !value)
              setScopeBaseRevision(space.revision)
              setNextScope(null)
            }}
          >
            更改学习范围
          </button>
        )}
        {showScope && !archived && (
          <form
            className="stack-form"
            aria-label="更改学习范围"
            onSubmit={(event) => {
              event.preventDefault()
              if (pending || !nextScope) return
              void run(
                (signal) =>
                  studyApi.updateScope(
                    space.space_id,
                    { expected_revision: scopeBaseRevision, scope: nextScope },
                    signal,
                  ),
                (next) => {
                  client.setQueryData(studyKeys.space(identity, space.space_id), next)
                  setScopeRevision(next.scope_revision)
                  resetEditors()
                  setSettingsVersion((value) => value + 1)
                },
              )
            }}
          >
            <p className="muted tiny">保存会新增一个固定范围版本，已有目标与单元继续保留原范围。</p>
            <StudyScopePicker value={nextScope} onChange={setNextScope} disabled={pending} />
            <button type="submit" className="button primary" disabled={pending || !nextScope}>
              保存新范围
            </button>
          </form>
        )}
      </section>
      <section className="card stack-form" aria-label="学习概念" style={wrap}>
        <h2>学习概念</h2>
        {concepts.isPending ? (
          <Loading>正在读取概念…</Loading>
        ) : !concepts.data?.items.length ? (
          <p className="muted">还没有学习概念，可以先添加一个想掌握的知识点。</p>
        ) : (
          <ul className="document-options">
            {concepts.data.items.map((item) => (
              <li key={item.concept_id} style={wrap}>
                <div className="button-row">
                  {item.source_status === 'revoked' ? (
                    <span>资料已失效的概念</span>
                  ) : (
                    <Link to={`/study/concepts/${encodeURIComponent(item.concept_id)}`}>
                      {item.title}
                    </Link>
                  )}
                  <span className="muted tiny">范围版本 {item.scope_revision}</span>
                  {!archived && item.source_status === 'active' && (
                    <button
                      type="button"
                      className="text-button"
                      aria-label={`编辑概念：${item.title}`}
                      disabled={pending}
                      onClick={() => {
                        setEditingConcept(item)
                        setShowConcept(true)
                      }}
                    >
                      编辑
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {!archived && !showConcept && (
          <button
            type="button"
            className="button secondary"
            disabled={pending || !scoped}
            onClick={() => {
              setEditingConcept(null)
              setShowConcept(true)
            }}
          >
            添加概念
          </button>
        )}
        {showConcept && !archived && (
          <ConceptEditor
            key={`${editingConcept?.concept_id || 'new'}:${scopeRevision}`}
            concept={editingConcept}
            disabled={pending}
            onSubmit={saveConcept}
            onCancel={() => {
              setShowConcept(false)
              setEditingConcept(null)
            }}
          />
        )}
      </section>
      <section className="card stack-form" aria-label="学习目标列表" style={wrap}>
        <h2>学习目标</h2>
        {goals.isPending ? (
          <Loading>正在读取学习目标…</Loading>
        ) : !goals.data?.items.length ? (
          <p className="muted">还没有学习目标，设置目标后可以添加学习单元。</p>
        ) : (
          <ul className="document-options">
            {goals.data.items.map((item) => (
              <li key={item.goal_id} style={wrap}>
                <p>{item.source_status === 'revoked' ? '资料已失效的学习目标' : item.title}</p>
                <p className="muted tiny">
                  {studyPlanLabels[item.status]} · 每日 {item.daily_minutes} 分钟 · 范围版本{' '}
                  {item.scope_revision}
                  {item.deadline ? ` · 计划完成 ${item.deadline}` : ''}
                </p>
                {item.source_status === 'active' && (
                  <div className="button-row">
                    {!archived && (
                      <button
                        type="button"
                        className="text-button"
                        disabled={pending}
                        aria-label={`编辑目标：${item.title}`}
                        onClick={() => {
                          setEditingGoal(item)
                          setShowGoal(true)
                        }}
                      >
                        编辑目标
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-button"
                      disabled={pending}
                      aria-label={`查看单元：${item.title}`}
                      onClick={() => {
                        setSelectedGoal(item)
                        setShowUnit(false)
                        setEditingUnit(null)
                      }}
                    >
                      查看单元
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {!archived && !showGoal && (
          <button
            type="button"
            className="button secondary"
            disabled={pending || !scoped}
            onClick={() => {
              setEditingGoal(null)
              setShowGoal(true)
            }}
          >
            添加学习目标
          </button>
        )}
        {showGoal && !archived && (
          <GoalEditor
            goal={editingGoal || undefined}
            scopeRevision={editingGoal?.scope_revision || scopeRevision}
            disabled={pending}
            onSubmit={saveGoal}
            onCancel={() => {
              setShowGoal(false)
              setEditingGoal(null)
            }}
          />
        )}
      </section>
      {selectedGoal && (
        <section className="card stack-form" aria-label="学习单元列表" style={wrap}>
          <h2>{selectedGoal.title} · 学习单元</h2>
          {units.isPending ? (
            <Loading>正在读取学习单元…</Loading>
          ) : !units.data?.items.length ? (
            <p className="muted">还没有学习单元，可以按章节逐步安排。</p>
          ) : (
            <ol className="document-options">
              {units.data.items.map((item, index, all) => (
                <li key={item.unit_id} style={wrap}>
                  <p>{item.source_status === 'revoked' ? '资料已失效的学习单元' : item.title}</p>
                  <p className="muted tiny">
                    {studyPlanLabels[item.status]} · 固定范围版本 {item.scope_revision}
                  </p>
                  {!archived && item.source_status === 'active' && (
                    <div className="button-row">
                      <button
                        type="button"
                        className="text-button"
                        disabled={pending}
                        aria-label={`编辑单元：${item.title}`}
                        onClick={() => {
                          setEditingUnit(item)
                          setShowUnit(true)
                        }}
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        disabled={
                          pending ||
                          index === 0 ||
                          all.some((entry) => entry.source_status === 'revoked')
                        }
                        aria-label={`上移：${item.title}`}
                        onClick={() => moveUnit(item.unit_id, -1)}
                      >
                        上移
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        disabled={
                          pending ||
                          index === all.length - 1 ||
                          all.some((entry) => entry.source_status === 'revoked')
                        }
                        aria-label={`下移：${item.title}`}
                        onClick={() => moveUnit(item.unit_id, 1)}
                      >
                        下移
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
          {!archived && !showUnit && (
            <button
              type="button"
              className="button secondary"
              disabled={pending || !scoped || !units.data || units.data.items.length >= 100}
              onClick={() => {
                setEditingUnit(null)
                setShowUnit(true)
              }}
            >
              添加学习单元
            </button>
          )}
          {showUnit && !archived && scoped && units.data && (
            <UnitEditor
              key={`${selectedGoal.goal_id}:${editingUnit?.unit_id || 'new'}:${scopeRevision}`}
              unit={editingUnit}
              scope={scoped}
              scopeRevision={scopeRevision}
              position={units.data.items.length}
              disabled={pending}
              onSubmit={saveUnit}
              onCancel={() => {
                setShowUnit(false)
                setEditingUnit(null)
              }}
            />
          )}
        </section>
      )}
    </div>
  )
}

function SpaceSettings({
  space,
  disabled,
  onSubmit,
  onReload,
}: {
  space: StudySpace
  disabled: boolean
  onSubmit: (data: StudySpaceUpdate) => void
  onReload: () => void
}) {
  const [draft, setDraft] = useState(space)
  const [dirty, setDirty] = useState(false)
  const [title, setTitle] = useState(space.title)
  const [timezone, setTimezone] = useState(space.timezone)
  const stale = space.revision !== draft.revision
  useEffect(() => {
    if (dirty || !stale) return
    setDraft(space)
    setTitle(space.title)
    setTimezone(space.timezone)
  }, [space, dirty, stale])
  let validTimezone = false
  try {
    new Intl.DateTimeFormat('zh-CN', { timeZone: timezone })
    validTimezone = !!timezone.trim()
  } catch {
    /* The input is not a supported timezone. */
  }
  const valid = !!title.trim() && title.trim().length <= 80 && validTimezone
  function submit(event: FormEvent) {
    event.preventDefault()
    if (disabled || stale || !valid) return
    onSubmit({ expected_revision: draft.revision, title: title.trim(), timezone: timezone.trim() })
  }
  return (
    <form className="stack-form" aria-label="学习空间设置" onSubmit={submit}>
      <fieldset className="stack-form" disabled={disabled || stale}>
        <label>
          空间名称
          <input
            value={title}
            maxLength={80}
            required
            onChange={(event) => {
              setDirty(true)
              setTitle(event.target.value)
            }}
          />
        </label>
        <label>
          学习时区
          <input
            value={timezone}
            maxLength={64}
            placeholder="Asia/Shanghai"
            onChange={(event) => {
              setDirty(true)
              setTimezone(event.target.value)
            }}
          />
        </label>
        <button type="submit" className="button primary" disabled={disabled || stale || !valid}>
          保存空间
        </button>
      </fieldset>
      {stale && (
        <div className="stack-form">
          <p className="notice" role="alert">
            空间已在其他位置更新，请重新加载后编辑。
          </p>
          <button type="button" className="button secondary" disabled={disabled} onClick={onReload}>
            重新加载
          </button>
        </div>
      )}
    </form>
  )
}

function ConceptEditor({
  concept,
  disabled,
  onSubmit,
  onCancel,
}: {
  concept: StudyConcept | null
  disabled: boolean
  onSubmit: (title: string) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(concept?.title || '')
  return (
    <form
      className="stack-form"
      aria-label="学习概念编辑"
      onSubmit={(event) => {
        event.preventDefault()
        if (!disabled && title.trim() && title.trim().length <= 80) onSubmit(title.trim())
      }}
    >
      <label>
        概念名称
        <input
          required
          maxLength={80}
          value={title}
          disabled={disabled}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <div className="button-row">
        <button type="submit" className="button primary" disabled={disabled || !title.trim()}>
          保存概念
        </button>
        <button type="button" className="button secondary" disabled={disabled} onClick={onCancel}>
          取消编辑
        </button>
      </div>
    </form>
  )
}

function UnitEditor({
  unit,
  scope,
  scopeRevision,
  position,
  disabled,
  onSubmit,
  onCancel,
}: {
  unit: StudyUnit | null
  scope: StudyScope
  scopeRevision: number
  position: number
  disabled: boolean
  onSubmit: (data: StudyUnitCreate) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(unit?.title || '')
  const [status, setStatus] = useState<StudyUnit['status']>(unit?.status || 'planned')
  const [selection, setSelection] = useState<SourceScope | null>(unit?.scope || null)
  return (
    <form
      className="stack-form"
      aria-label="学习单元"
      onSubmit={(event) => {
        event.preventDefault()
        if (disabled || !title.trim() || title.trim().length > 80 || !selection) return
        onSubmit({
          title: title.trim(),
          status,
          scope: selection,
          scope_revision: unit?.scope_revision || scopeRevision,
          position: unit?.position ?? position,
        })
      }}
    >
      <fieldset className="stack-form" disabled={disabled}>
        <label>
          单元名称
          <input
            required
            maxLength={80}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          单元状态
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as StudyUnit['status'])}
          >
            {Object.entries(studyPlanLabels).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {unit ? (
          <p className="muted tiny">
            此单元使用固定范围版本 {unit.scope_revision}，创建后资料选择保持不变。
          </p>
        ) : (
          <StudyScopePicker
            scope={scope}
            scopeRevision={scopeRevision}
            value={selection}
            onChange={setSelection}
            disabled={disabled}
          />
        )}
        <div className="button-row">
          <button
            type="submit"
            className="button primary"
            disabled={disabled || !title.trim() || !selection}
          >
            保存单元
          </button>
          <button type="button" className="button secondary" disabled={disabled} onClick={onCancel}>
            取消编辑
          </button>
        </div>
      </fieldset>
    </form>
  )
}
