import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, BookOpen, FileText, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, PageHeading, StatusBadge } from '../../components/ui'
import { Dialog } from '../../components/Dialog'
import { StudyScopePicker, documentSelectionVersion } from '../../features/study/StudyScopePicker'
import { DocumentUpload } from '../../features/knowledge/DocumentUpload'
import { useCourseOperation } from '../../features/courses/useCourseOperation'
import { CourseCreateOptions, type CourseCreateOptionsValue } from '../../features/courses/CourseCreateOptions'
import { CourseOperationNotice } from '../../features/courses/CourseOperationNotice'
import { CourseSourcePreview } from '../../features/courses/CourseSourcePreview'
import { isUnconfirmedCourseOperation } from '../../features/courses/courseActionState'
import { previewSelectionKey } from '../../features/courses/courseSourceFacts'
import { api } from '../../services/api'
import {
  courseErrorMessage,
  courseKeys,
  coursesApi,
  createCourseSubmissionKeys,
} from '../../services/courses'
import { coursePath } from '../../services/courseNavigation'
import { clearCourseDraft, loadCourseDraft, saveCourseDraft } from '../../services/courseDrafts'
import { recordExperienceEvent } from '../../services/experienceEvents'
import { ApiError } from '../../services/http'
import type { DocumentItem, SourceScope } from '../../types/api'
import type { CourseCreate, CourseSourcePolicy, CourseTeachingMode } from '../../types/course'
import '../../styles/courses.scss'

export function CourseCreatePage() {
  const identity = useIdentityKey()
  return <CourseCreateForm key={identity} identity={identity} />
}

function CourseCreateForm({ identity }: { identity: string | number }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const operation = useCourseOperation()
  const keyFor = useMemo(() => createCourseSubmissionKeys(identity, 'new'), [identity])
  const [draft] = useState(() => loadCourseDraft(identity))
  const [topic, setTopic] = useState(draft?.topic || '')
  const [goal, setGoal] = useState(draft?.goal || '')
  const [prior, setPrior] = useState(draft?.prior_knowledge || '')
  const [minutes, setMinutes] = useState(draft?.daily_minutes ?? 20)
  const [count, setCount] = useState(draft?.lesson_count ?? 6)
  const [timezone, setTimezone] = useState(draft?.timezone || 'Asia/Shanghai')
  const [preload, setPreload] = useState(draft?.preload_first_lesson ?? true)
  const [teachingMode, setTeachingMode] = useState<CourseTeachingMode>(draft?.teaching_mode || 'guided')
  const [modeChanged, setModeChanged] = useState(false)
  const [source, setSource] = useState<CourseSourcePolicy>(draft?.source_policy || 'topic')
  const [scope, setScope] = useState<SourceScope | null>(draft?.scope || null)
  const [scopeVersions, setScopeVersions] = useState(draft?.document_versions || {})
  const [uploading, setUploading] = useState(false)
  const [uploadedDocument, setUploadedDocument] = useState<DocumentItem | null>(null)
  const [preview, setPreview] = useState<{ docId: string; version: string; selection: string } | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(() => !!draft && (
    !!draft.goal || !!draft.prior_knowledge || draft.daily_minutes !== 20 || draft.lesson_count !== 6 ||
    draft.timezone !== 'Asia/Shanghai' || !draft.preload_first_lesson
  ))
  const advanced = useRef<HTMLDetailsElement>(null)
  const intent = useRef<{ body: CourseCreate; semantic: string } | null>(null)
  const viewed = useRef(false)
  const capabilities = useQuery({
    queryKey: courseKeys.capabilities(identity),
    queryFn: ({ signal }) => coursesApi.capabilities(signal),
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
  })
  const teachingAgentsAvailable = capabilities.isSuccess && !capabilities.error && Array.isArray(capabilities.data.teaching_modes)
    ? capabilities.data.teaching_modes.includes('guided') : null
  const effectiveTeachingMode = operation.state.kind === 'unconfirmed' && intent.current?.body.teaching_mode
    ? intent.current.body.teaching_mode
    : teachingAgentsAvailable === false ? 'fast' : teachingMode
  const modeAvailable = teachingAgentsAvailable !== null && capabilities.data?.teaching_modes.includes(effectiveTeachingMode)
  useEffect(() => {
    if (viewed.current) return
    viewed.current = true
    void recordExperienceEvent({ event_id: crypto.randomUUID(), name: 'course_create_viewed' })
  }, [])
  const catalog = useQuery({
    queryKey: [identity, 'documents'],
    queryFn: ({ signal }) => api.documents(signal),
    enabled: source === 'strict_docs',
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchInterval: (state) =>
      (state.state.data?.items || []).some((doc) =>
        ['processing', 'pending', 'queued', 'running'].includes(doc.status),
      )
        ? 3500
        : false,
    refetchIntervalInBackground: false,
  })
  const changeScope = useCallback(
    (next: SourceScope | null) => {
      setPreview(null)
      setScope(next)
      setScopeVersions(
        Object.fromEntries(
          (next?.documents || []).flatMap((selected) => {
            const doc = catalog.data?.items.find((item) => item.doc_id === selected.doc_id)
            return doc ? [[selected.doc_id, documentSelectionVersion(doc)]] : []
          }),
        ),
      )
    },
    [catalog.data],
  )
  useEffect(() => {
    saveCourseDraft(identity, {
      topic,
      goal,
      prior_knowledge: prior,
      daily_minutes: minutes,
      lesson_count: count,
      timezone,
      preload_first_lesson: preload,
      teaching_mode: effectiveTeachingMode,
      source_policy: source,
      scope,
      document_versions: scopeVersions,
    })
  }, [identity, topic, goal, prior, minutes, count, timezone, preload, effectiveTeachingMode, source, scope, scopeVersions])
  const previewDocument = preview && source === 'strict_docs' && !catalog.error
    ? catalog.data?.items.find((document) => document.doc_id === preview.docId && document.status === 'ready' &&
      documentSelectionVersion(document) === preview.version) : null
  const previewSelection = preview && scope?.documents.find((selection) =>
    selection.doc_id === preview.docId && previewSelectionKey(selection) === preview.selection)
  const activePreview = !!previewDocument && !!previewSelection
  useEffect(() => {
    if (preview && !activePreview) setPreview(null)
  }, [preview, activePreview])
  const uploaded = uploadedDocument && (catalog.data?.items.find((document) => document.doc_id === uploadedDocument.doc_id) || uploadedDocument)
  const readySelection =
    source === 'topic' ||
    (!catalog.error &&
      !catalog.isFetching &&
      !!scope?.documents.length &&
      scope.documents.every((selected) =>
        catalog.data?.items.some(
          (doc) =>
            doc.doc_id === selected.doc_id &&
            doc.status === 'ready' &&
            scopeVersions[selected.doc_id] === documentSelectionVersion(doc),
        ),
      ))
  const pending = operation.pending !== null
  const unknown = operation.state.kind === 'unconfirmed'
  const locked = pending || unknown
  function updateOptions(patch: Partial<CourseCreateOptionsValue>) {
    if (patch.goal !== undefined) setGoal(patch.goal || '')
    if (patch.prior_knowledge !== undefined) setPrior(patch.prior_knowledge || '')
    if (patch.daily_minutes !== undefined) setMinutes(patch.daily_minutes)
    if (patch.lesson_count !== undefined) setCount(patch.lesson_count)
    if (patch.timezone !== undefined) setTimezone(patch.timezone)
    if (patch.preload_first_lesson !== undefined) setPreload(patch.preload_first_lesson)
  }
  async function create(saved: { body: CourseCreate; semantic: string }) {
    await operation.run('create', async (signal) => {
      try {
        const key = await keyFor('create', saved.semantic)
        if (signal.aborted) throw new DOMException('已离开页面', 'AbortError')
        const task = await coursesApi.create(saved.body, key, signal)
        if (!task?.course_id || !task.task_id) throw new ApiError('创建结果尚未确认', 0, 'INVALID_RESPONSE')
        return task
      } catch (error) {
        if (!isUnconfirmedCourseOperation(error)) intent.current = null
        if (error instanceof ApiError && error.status === 409 && String(error.code).toLowerCase() === 'teaching_agents_unavailable') {
          setModeChanged(true)
          await capabilities.refetch()
        }
        throw error
      }
    }, (task) => {
      intent.current = null
      keyFor.settle('create', saved.semantic)
      clearCourseDraft(identity)
      client.setQueryData(courseKeys.task(identity, task.course_id, task.task_id, task.lesson_id), task)
      void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
      void recordExperienceEvent({ event_id: crypto.randomUUID(), name: 'course_create_submitted', course_id: task.course_id, task_id: task.task_id })
      navigate(coursePath(task.course_id))
    })
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (locked || !modeAvailable) return
    if (!topic.trim()) {
      operation.setError('请填写要学习的主题。')
      return
    }
    if (
      !Number.isInteger(minutes) ||
      minutes < 5 ||
      minutes > 120 ||
      !Number.isInteger(count) ||
      count < 1 ||
      count > 10
    ) {
      setAdvancedOpen(true)
      operation.setError('每天学习时长须为 5–120 分钟，课时数须为 1–10 节。')
      return
    }
    if (!readySelection) {
      operation.setError('请选择已经处理完成的资料，再创建课程。')
      return
    }
    try {
      new Intl.DateTimeFormat('zh-CN', { timeZone: timezone.trim() }).format()
    } catch {
      setAdvancedOpen(true)
      operation.setError('请填写有效的学习时区，例如 Asia/Shanghai。')
      return
    }
    const body: CourseCreate = {
      topic: topic.trim(),
      goal: goal.trim(),
      prior_knowledge: prior.trim(),
      daily_minutes: minutes,
      lesson_count: count,
      preload_first_lesson: preload,
      teaching_mode: effectiveTeachingMode,
      // guided reviews as part of its mode; fast does not request an extra review pass.
      request_quality_review: false,
      source_policy: source,
      scope: source === 'strict_docs' ? scope : null,
      timezone: timezone.trim(),
    }
    const semantic = JSON.stringify(body)
    intent.current = { body, semantic }
    setModeChanged(false)
    await create(intent.current)
  }
  return (
    <div className="course-create-page">
      <Link to="/study" className="back-link">
        <ArrowLeft size={16} />
        我的课程
      </Link>
      <PageHeading
        eyebrow="循课 · 从目标开始"
        title="开始一门课程"
        description="先准备学习纲要，再按你的节奏逐课学习。"
      />
      <div className="course-create-layout">
        <section className="card">
          <form
            className="stack-form course-create-form"
            onInvalidCapture={(event) => {
              const field = event.target as HTMLElement
              if (!field.closest('details') || !advanced.current) return
              advanced.current.open = true
              setAdvancedOpen(true)
              queueMicrotask(() => field.focus())
            }}
            onSubmit={(event) => {
              void submit(event)
            }}
          >
            <fieldset disabled={locked} className="course-form-fields">
              <label>
                学习主题 <span className="muted tiny">必填</span>
                <textarea
                  required
                  rows={3}
                  maxLength={2000}
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  placeholder="例如：Python 函数入门"
                />
              </label>
              <fieldset className="source-fieldset">
                <legend>课程来源</legend>
                <div className="source-choices">
                  <label className={`choice-card ${source === 'topic' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="course-source"
                      checked={source === 'topic'}
                      onChange={() => { setSource('topic'); setPreview(null) }}
                    />
                    <Sparkles size={21} />
                    <span>
                      <strong>围绕一个主题</strong>
                      <small>基于模型通用知识组织课程</small>
                    </span>
                  </label>
                  <label className={`choice-card ${source === 'strict_docs' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="course-source"
                      checked={source === 'strict_docs'}
                      onChange={() => setSource('strict_docs')}
                    />
                    <FileText size={21} />
                    <span>
                      <strong>根据我的资料</strong>
                      <small>仅使用所选资料，保留原文引用</small>
                    </span>
                  </label>
                </div>
              </fieldset>
              {source === 'strict_docs' && (
                <div className="course-source-picker">
                  <StudyScopePicker
                    value={scope}
                    onChange={changeScope}
                    initialVersions={scopeVersions}
                    disabled={locked}
                    onPreview={(document, selection) => setPreview({
                      docId: document.doc_id,
                      version: documentSelectionVersion(document),
                      selection: previewSelectionKey(selection),
                    })}
                  />
                  {previewDocument && previewSelection && (
                    <CourseSourcePreview
                      document={previewDocument}
                      selection={previewSelection}
                      onClose={() => setPreview(null)}
                      onReloadCatalog={() => {
                        setPreview(null)
                        void catalog.refetch()
                      }}
                    />
                  )}
                  {uploaded && <p className="notice" role="status">
                    已收到：{uploaded.file_name}。{uploaded.status === 'ready'
                      ? '资料已就绪，请在列表中核对并选择。'
                      : ['failed', 'needs_reupload'].includes(uploaded.status)
                        ? '资料处理未完成，请重新上传；课程草稿已保留。'
                        : '正在处理，完成后请在列表中核对并选择。'}
                  </p>}
                  {!!catalog.data?.items.some((doc) => doc.status !== 'ready') && (
                    <div className="course-processing-docs">
                      <p className="muted tiny">以下资料暂不能用于创建课程：</p>
                      {catalog.data.items
                        .filter((doc) => doc.status !== 'ready')
                        .map((doc) => (
                          <div key={doc.doc_id} className="course-processing-item">
                            <span>{doc.file_name}
                              {['failed', 'needs_reupload'].includes(doc.status) &&
                                <small className="muted">处理未完成，请重新上传资料。</small>}
                            </span>
                            <StatusBadge status={doc.status} />
                          </div>
                        ))}
                    </div>
                  )}
                  <button type="button" className="text-button" onClick={() => setUploading(true)}>
                    上传资料
                    <ArrowRight size={14} />
                  </button>
                  <p className="tiny muted">资料不足的课时会标注缺口；补充资料后可创建新课程。</p>
                </div>
              )}
              <fieldset className="source-fieldset course-teaching-modes" disabled={locked || teachingAgentsAvailable === null}>
                <legend>教学方式</legend>
                <div className="source-choices">
                  <label className={`choice-card ${effectiveTeachingMode === 'guided' ? 'selected' : ''}`}>
                    <input type="radio" name="teaching-mode" value="guided"
                      disabled={teachingAgentsAvailable !== true}
                      checked={effectiveTeachingMode === 'guided'} onChange={() => setTeachingMode('guided')} />
                    <span><strong>{teachingAgentsAvailable === false ? '标准教学（暂不可用）' : '标准教学（推荐）'}</strong>
                      <small>先设计课程，再生成讲解并做教学检查</small></span>
                  </label>
                  <label className={`choice-card ${effectiveTeachingMode === 'fast' ? 'selected' : ''}`}>
                    <input type="radio" name="teaching-mode" value="fast"
                      disabled={teachingAgentsAvailable !== null && !capabilities.data?.teaching_modes.includes('fast')}
                      checked={effectiveTeachingMode === 'fast'} onChange={() => setTeachingMode('fast')} />
                    <span><strong>快速生成</strong><small>直接生成，适合快速了解</small></span>
                  </label>
                </div>
                {teachingAgentsAvailable === false && effectiveTeachingMode === 'fast' && <p className="notice">本课程使用快速生成，未执行教学检查。</p>}
              </fieldset>
              {teachingAgentsAvailable === null && (capabilities.isPending
                ? <p className="muted tiny" role="status">正在确认可用的教学方式…</p>
                : <ErrorNotice error="暂时无法确认教学方式，请重新读取后创建课程。" onRetry={() => { void capabilities.refetch() }} />)}
              {modeChanged && <p className="notice" role="status">教学方式的可用状态已变化，请核对上方选择后再次提交。</p>}
              <details ref={advanced} className="course-create-advanced" open={advancedOpen}
                onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
                <summary>调整学习安排 · 每天 {Number.isFinite(minutes) ? minutes : '—'} 分钟 · {Number.isFinite(count) ? count : '—'} 课</summary>
                <CourseCreateOptions
                  value={{ goal, prior_knowledge: prior, daily_minutes: minutes, lesson_count: count, timezone, preload_first_lesson: preload }}
                  onChange={updateOptions}
                  disabled={locked}
                />
              </details>
            </fieldset>
            {operation.state.kind === 'idle' && <ErrorNotice error={operation.error ? courseErrorMessage(operation.error) : null} />}
            <CourseOperationNotice state={operation.state} error={operation.error} disabled={pending}
              onRecover={unknown && intent.current ? () => { if (intent.current) void create(intent.current) } : undefined}
              recoveryLabel="重试原创建请求" />
            {unknown && <p className="tiny muted">表单保留本次提交内容。可先<Link className="text-link" to="/study">查看已创建的课程</Link>；重试使用同一请求标识。</p>}
            <div className="composer-footer">
              <span className="tiny muted">草稿保留在当前浏览器会话中</span>
              <button
                className="button primary"
                type="submit"
                disabled={locked || !modeAvailable || !topic.trim() || !readySelection}
              >
                {pending ? '正在创建…' : operation.error ? '重试创建课程' : '生成课程纲要'}
                <ArrowRight size={17} />
              </button>
            </div>
          </form>
        </section>
        <aside className="journey-card course-create-aside">
          <BookOpen size={32} />
          <h2>把一个目标，变成每天的一小步。</h2>
          <ol>
            <li>
              <strong>先看纲要</strong>
              <p>查看每课目标；勾选立即准备时，第一课会自动开始生成。</p>
            </li>
            <li>
              <strong>逐课学习</strong>
              <p>第一课就绪即可阅读，其余课时点击准备，随时回来接着读。</p>
            </li>
            <li>
              <strong>用 3 题检验理解</strong>
              <p>记录首次表现，再针对错题补练。</p>
            </li>
          </ol>
          <p className="tiny muted">
            主题课程不联网检索，内容以通用知识为基础；资料课程可回到保存的原文核对。
          </p>
        </aside>
      </div>
      {uploading && (
        <Dialog title="上传课程资料" className="wide-dialog" onClose={() => setUploading(false)}>
          <DocumentUpload
            onUploaded={(document) => {
              setUploadedDocument(document)
              void client.invalidateQueries({ queryKey: [identity, 'documents'] })
            }}
          />
          <p className="muted tiny">
            上传和处理期间，学习目标与课程草稿都会保留。处理完成后返回选择资料。
          </p>
          <button type="button" className="button secondary" onClick={() => setUploading(false)}>
            返回课程草稿
          </button>
        </Dialog>
      )}
    </div>
  )
}
