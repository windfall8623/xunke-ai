import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  FileText,
  Globe2,
  Lightbulb,
  Sparkles,
  Target,
} from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../app/AuthProvider'
import { ErrorNotice, Loading } from '../components/ui'
import { CourseListSection } from '../features/courses/CourseListSection'
import { api } from '../services/api'
import type { Difficulty, GenerateRequest, SelectedDocument } from '../types/api'

export function HomePage() {
  const { user } = useAuth()
  const identity = useIdentityKey()
  const navigate = useNavigate()
  const [goal, setGoal] = useState('')
  const [count, setCount] = useState(5)
  const [difficulty, setDifficulty] = useState<Difficulty>('mixed')
  const [source, setSource] = useState<'topic' | 'documents'>('topic')
  const [allowWeb, setAllowWeb] = useState(false)
  const [images, setImages] = useState(false)
  const [documents, setDocuments] = useState<Record<string, SelectedDocument>>({})
  const [validation, setValidation] = useState('')
  const requestIdentity = useRef<{ body: string; key: string } | null>(null)
  const catalog = useQuery({
    queryKey: [identity, 'documents'],
    queryFn: ({ signal }) => api.documents(signal),
    enabled: !!user,
  })
  const generate = useMutation({
    mutationFn: (data: GenerateRequest) => {
      const body = JSON.stringify(data)
      if (requestIdentity.current?.body !== body)
        requestIdentity.current = { body, key: crypto.randomUUID() }
      return api.generate(data, requestIdentity.current.key)
    },
    onSuccess: (result) => navigate(`/tasks/${encodeURIComponent(result.task_id)}`),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!user) {
      navigate('/login', { state: { from: '/' } })
      return
    }
    if (!goal.trim()) {
      setValidation('请先填写这次的学习目标。')
      return
    }
    if (source === 'documents' && !Object.keys(documents).length) {
      setValidation('请选择 1–5 篇已经处理完成的资料。')
      return
    }
    setValidation('')
    const data: GenerateRequest = {
      user_input: goal.trim(),
      question_count: count,
      difficulty,
      generate_images: images,
      source_policy: source === 'topic' ? 'topic' : allowWeb ? 'doc_plus_web' : 'strict_docs',
    }
    if (source === 'documents')
      data.scope = { type: 'selected_documents', documents: Object.values(documents) }
    if (!generate.isPending) generate.mutate(data)
  }
  return (
    <div className="home-page">
      <header className="home-heading">
        <div>
          <p className="eyebrow">
            <span className="small-dot" /> 你的下一次进步，从这里开始
          </p>
          <h1>
            今天，想学点什么<span className="accent">？</span>
          </h1>
          <p className="muted">从一门课程开始，按节学习、练习并回顾。</p>
        </div>
        <div className="heading-art" aria-hidden="true">
          <span className="art-spark">✦</span>
          <div className="art-card">
            <BookOpen size={46} strokeWidth={1.4} />
            <span>
              LEARN
              <br />
              SOMETHING NEW
            </span>
          </div>
          <div className="art-check">
            <Check size={23} />
          </div>
        </div>
      </header>
      <CourseListSection compact />
      <div className="home-grid">
        <section className="card composer">
          <div className="card-heading">
            <span className="icon-tile indigo">
              <Sparkles size={21} />
            </span>
            <div>
              <h2>自由练习</h2>
              <p>也可以围绕一个目标，单独生成一组题目。</p>
            </div>
          </div>
          <form onSubmit={submit}>
            <div className="field-label">
              <label htmlFor="learning-goal">学习目标</label>
              <span className="field-meta">越具体，练习越有针对性</span>
            </div>
            <div className="goal-field">
              <textarea
                id="learning-goal"
                value={goal}
                maxLength={2000}
                onChange={(event) => setGoal(event.target.value)}
                placeholder="例如：帮我理解概率中的条件概率与贝叶斯定理，重点练习实际应用。"
                rows={4}
              />
              <span>{goal.length} / 2000</span>
            </div>
            <div className="prompt-suggestions">
              <span>
                <Lightbulb size={14} />
                试试
              </span>
              {['Python 基础', '中国古代史', '微积分入门'].map((item) => (
                <button
                  type="button"
                  key={item}
                  onClick={() => setGoal(`学习${item}，掌握核心概念并通过例题巩固。`)}
                >
                  {item}
                </button>
              ))}
            </div>
            <fieldset className="source-fieldset">
              <legend>练习来源</legend>
              <div className="source-choices">
                <label className={`choice-card ${source === 'topic' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="source"
                    checked={source === 'topic'}
                    onChange={() => setSource('topic')}
                  />
                  <Globe2 size={21} />
                  <span>
                    <strong>围绕一个主题</strong>
                    <small>探索新知识，巩固通用概念</small>
                  </span>
                </label>
                <label className={`choice-card ${source === 'documents' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="source"
                    checked={source === 'documents'}
                    onChange={() => setSource('documents')}
                  />
                  <FileText size={21} />
                  <span>
                    <strong>根据我的资料</strong>
                    <small>专注所选内容，回到原文理解</small>
                  </span>
                </label>
              </div>
            </fieldset>
            {source === 'documents' && (
              <div className="source-selection">
                <div className="section-line">
                  <strong>
                    选择资料 <span className="muted">{Object.keys(documents).length} / 5</span>
                  </strong>
                  <Link to="/knowledge" className="text-link">
                    管理资料
                    <ArrowRight size={13} />
                  </Link>
                </div>
                {!user ? (
                  <p className="muted">登录后，上传资料并选择本次练习的范围。</p>
                ) : catalog.isPending ? (
                  <Loading>正在读取资料…</Loading>
                ) : catalog.error ? (
                  <ErrorNotice
                    error={catalog.error}
                    onRetry={() => {
                      void catalog.refetch()
                    }}
                  />
                ) : !catalog.data?.items.some((doc) => doc.status === 'ready') ? (
                  <p className="muted">还没有可用资料。上传并处理完成后即可开始。</p>
                ) : (
                  <div className="document-options">
                    {catalog.data.items
                      .filter((doc) => doc.status === 'ready')
                      .map((doc) => (
                        <div key={doc.doc_id}>
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={!!documents[doc.doc_id]}
                              disabled={
                                !documents[doc.doc_id] && Object.keys(documents).length >= 5
                              }
                              onChange={(event) =>
                                setDocuments((current) => {
                                  const next = { ...current }
                                  if (event.target.checked)
                                    next[doc.doc_id] = { doc_id: doc.doc_id }
                                  else delete next[doc.doc_id]
                                  return next
                                })
                              }
                            />
                            <FileText size={16} />
                            <span>{doc.file_name}</span>
                          </label>
                          {documents[doc.doc_id] &&
                            !!doc.sections?.length &&
                            doc.section_catalog_revision && (
                              <fieldset className="section-options">
                                <legend>选填：限定章节；不选时使用全文</legend>
                                {doc.sections.map((section) => (
                                  <label className="checkbox-row" key={section.section_id}>
                                    <input
                                      type="checkbox"
                                      checked={
                                        documents[doc.doc_id].section_ids?.includes(
                                          section.section_id,
                                        ) || false
                                      }
                                      onChange={(event) =>
                                        setDocuments((current) => {
                                          const selected = new Set(
                                            current[doc.doc_id]?.section_ids || [],
                                          )
                                          if (event.target.checked) selected.add(section.section_id)
                                          else selected.delete(section.section_id)
                                          return {
                                            ...current,
                                            [doc.doc_id]: {
                                              doc_id: doc.doc_id,
                                              ...(selected.size
                                                ? {
                                                    section_catalog_revision:
                                                      doc.section_catalog_revision,
                                                    section_ids: [...selected],
                                                  }
                                                : {}),
                                            },
                                          }
                                        })
                                      }
                                    />
                                    {section.title}
                                  </label>
                                ))}
                              </fieldset>
                            )}
                        </div>
                      ))}
                  </div>
                )}
                <label className="checkbox-row web-consent">
                  <input
                    type="checkbox"
                    checked={allowWeb}
                    onChange={(event) => setAllowWeb(event.target.checked)}
                  />
                  <span>
                    允许围绕学习主题联网补充
                    <small>默认仅依据所选资料；依据不足时会提示调整范围。</small>
                  </span>
                </label>
              </div>
            )}
            <div className="settings-row">
              <label>
                题目数量
                <select value={count} onChange={(event) => setCount(Number(event.target.value))}>
                  {[3, 4, 5, 6, 7, 8, 9, 10].map((value) => (
                    <option key={value} value={value}>
                      {value} 题{value === 5 ? ' · 推荐' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                练习难度
                <select
                  value={difficulty}
                  onChange={(event) => setDifficulty(event.target.value as Difficulty)}
                >
                  <option value="mixed">综合难度</option>
                  <option value="easy">入门 · 建立概念</option>
                  <option value="medium">进阶 · 加深理解</option>
                  <option value="hard">挑战 · 灵活应用</option>
                </select>
              </label>
            </div>
            <label className="checkbox-row image-consent">
              <input
                type="checkbox"
                checked={images}
                onChange={(event) => setImages(event.target.checked)}
              />
              添加辅助配图<span className="muted tiny">可选，可能增加等待时间</span>
            </label>
            <ErrorNotice error={validation || generate.error} />
            {generate.error && (
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setDocuments({})
                  void catalog.refetch()
                }}
              >
                刷新资料目录并重新选择
              </button>
            )}
            <div className="composer-footer">
              <span>
                <ShieldIcon />
                进度自动保存
              </span>
              <button type="submit" className="button secondary" disabled={generate.isPending}>
                {generate.isPending ? '正在创建…' : user ? '生成练习' : '登录并生成练习'}
                <ArrowRight size={18} />
              </button>
            </div>
          </form>
        </section>
        <aside className="home-aside">
          <section className="journey-card">
            <p className="eyebrow">不止是答对</p>
            <h2>
              让每一次练习，
              <br />
              都有新的收获。
            </h2>
            <ol className="journey-steps">
              <li>
                <span>
                  <Target size={18} />
                </span>
                <div>
                  <strong>从目标开始</strong>
                  <p>选定主题与范围，专注当下。</p>
                </div>
              </li>
              <li>
                <span>
                  <BookOpen size={18} />
                </span>
                <div>
                  <strong>在练习中理解</strong>
                  <p>即时反馈，看看答案为什么。</p>
                </div>
              </li>
              <li>
                <span>
                  <ArrowDownToLine size={18} />
                </span>
                <div>
                  <strong>回到依据，巩固薄弱点</strong>
                  <p>查看原文，再练一组。</p>
                </div>
              </li>
            </ol>
            <div className="journey-bottom">
              <span className="small-dot" /> 小小的坚持，也会走得很远
            </div>
          </section>
          <Link to="/demo" className="demo-card">
            <span className="icon-tile peach">
              <Sparkles size={20} />
            </span>
            <div>
              <strong>先体验，再出发</strong>
              <p>试试预置的「高效学习」练习</p>
              <span>
                无需登录 · 无 AI 调用
                <ArrowRight size={14} />
              </span>
            </div>
          </Link>
          <div className="source-note">
            <CheckCircle2 size={19} />
            <p>资料练习会保留可核验的来源。主题练习可能基于通用知识，请留意题目来源说明。</p>
          </div>
        </aside>
      </div>
    </div>
  )
}
function ShieldIcon() {
  return <CheckCircle2 size={15} />
}
