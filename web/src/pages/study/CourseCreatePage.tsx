import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, BookOpen, FileText, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, PageHeading, StatusBadge } from '../../components/ui'
import { Dialog } from '../../components/Dialog'
import { StudyScopePicker, documentSelectionVersion } from '../../features/study/StudyScopePicker'
import { DocumentUpload } from '../../features/knowledge/DocumentUpload'
import { useCourseOperation } from '../../features/courses/useCourseOperation'
import { api } from '../../services/api'
import {
  courseErrorMessage,
  courseKeys,
  coursesApi,
  createCourseSubmissionKeys,
} from '../../services/courses'
import { coursePath } from '../../services/courseNavigation'
import { clearCourseDraft, loadCourseDraft, saveCourseDraft } from '../../services/courseDrafts'
import type { SourceScope } from '../../types/api'
import type { CourseCreate, CourseSourcePolicy } from '../../types/course'
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
  const [source, setSource] = useState<CourseSourcePolicy>(draft?.source_policy || 'topic')
  const [scope, setScope] = useState<SourceScope | null>(draft?.scope || null)
  const [scopeVersions, setScopeVersions] = useState(draft?.document_versions || {})
  const [uploading, setUploading] = useState(false)
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
      source_policy: source,
      scope,
      document_versions: scopeVersions,
    })
  }, [identity, topic, goal, prior, minutes, count, timezone, source, scope, scopeVersions])
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
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
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
      operation.setError('请填写有效的学习时区，例如 Asia/Shanghai。')
      return
    }
    const body: CourseCreate = {
      topic: topic.trim(),
      goal: goal.trim(),
      prior_knowledge: prior.trim(),
      daily_minutes: minutes,
      lesson_count: count,
      source_policy: source,
      scope: source === 'strict_docs' ? scope : null,
      timezone: timezone.trim(),
    }
    const semantic = JSON.stringify(body)
    await operation.run(
      'create',
      async (signal) => {
        const key = await keyFor('create', semantic)
        if (signal.aborted) throw new DOMException('已离开页面', 'AbortError')
        return coursesApi.create(body, key, signal)
      },
      (task) => {
        keyFor.settle('create', semantic)
        clearCourseDraft(identity)
        client.setQueryData(
          courseKeys.task(identity, task.course_id, task.task_id, task.lesson_id),
          task,
        )
        void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
        navigate(coursePath(task.course_id))
      },
    )
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
            onSubmit={(event) => {
              void submit(event)
            }}
          >
            <fieldset disabled={pending} className="course-form-fields">
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
              <label>
                希望学会什么
                <textarea
                  rows={2}
                  maxLength={1000}
                  value={goal}
                  onChange={(event) => setGoal(event.target.value)}
                  placeholder="例如：能编写函数，并解释参数和返回值（选填）"
                />
              </label>
              <label>
                已有基础
                <textarea
                  rows={2}
                  maxLength={1000}
                  value={prior}
                  onChange={(event) => setPrior(event.target.value)}
                  placeholder="例如：会使用变量和循环（选填）"
                />
              </label>
              <div className="course-form-numbers">
                <label>
                  每天学习时长（分钟）
                  <input
                    type="number"
                    min={5}
                    max={120}
                    step={1}
                    required
                    value={Number.isNaN(minutes) ? '' : minutes}
                    onChange={(event) => setMinutes(event.target.valueAsNumber)}
                  />
                </label>
                <label>
                  课程节数
                  <input
                    type="number"
                    min={1}
                    max={10}
                    step={1}
                    required
                    value={Number.isNaN(count) ? '' : count}
                    onChange={(event) => setCount(event.target.valueAsNumber)}
                  />
                </label>
              </div>
              <label>
                学习时区
                <input
                  required
                  maxLength={100}
                  list="xunke-timezones"
                  value={timezone}
                  onChange={(event) => setTimezone(event.target.value)}
                />
                <datalist id="xunke-timezones">
                  {['Asia/Shanghai', 'Asia/Urumqi', 'Asia/Hong_Kong', 'Asia/Taipei', 'Asia/Singapore', 'Asia/Tokyo', 'Asia/Seoul', 'UTC', 'America/Los_Angeles', 'America/New_York', 'Europe/London', 'Europe/Berlin'].map((zone) => (
                    <option value={zone} key={zone} />
                  ))}
                </datalist>
                <small className="muted">按此时区安排每日复习，可直接选择常用时区。</small>
              </label>
              <fieldset className="source-fieldset">
                <legend>课程来源</legend>
                <div className="source-choices">
                  <label className={`choice-card ${source === 'topic' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="course-source"
                      checked={source === 'topic'}
                      onChange={() => setSource('topic')}
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
                    disabled={pending}
                  />
                  {!!catalog.data?.items.some((doc) => doc.status !== 'ready') && (
                    <div className="course-processing-docs">
                      <p className="muted tiny">以下资料暂不能用于创建课程：</p>
                      {catalog.data.items
                        .filter((doc) => doc.status !== 'ready')
                        .map((doc) => (
                          <div key={doc.doc_id}>
                            <span>{doc.file_name}</span>
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
            </fieldset>
            <ErrorNotice error={operation.error ? courseErrorMessage(operation.error) : null} />
            <div className="composer-footer">
              <span className="tiny muted">草稿保留在当前浏览器会话中</span>
              <button
                className="button primary"
                type="submit"
                disabled={pending || !topic.trim() || !readySelection}
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
              <p>查看每课目标，开课前可调整标题。</p>
            </li>
            <li>
              <strong>逐课学习</strong>
              <p>点击课时准备内容，随时回来接着读。</p>
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
            onUploaded={() => {
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
