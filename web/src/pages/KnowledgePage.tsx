import { useMutation, useQuery } from '@tanstack/react-query'
import { FileText, FolderOpen, RefreshCw, Replace, Search, ShieldCheck, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { Dialog } from '../components/Dialog'
import {
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusBadge,
  formatBytes,
  formatDate,
} from '../components/ui'
import { DocumentUpload } from '../features/knowledge/DocumentUpload'
import { api } from '../services/api'
import type { ApiSchemas, DocumentItem } from '../types/api'

export function KnowledgePage() {
  const identity = useIdentityKey()
  const [search, setSearch] = useState('')
  const [replace, setReplace] = useState<DocumentItem | null>(null)
  const [remove, setRemove] = useState<DocumentItem | null>(null)
  const [profiles, setProfiles] = useState<
    Record<string, ApiSchemas['ReindexBody']['index_profile_id']>
  >({})
  const query = useQuery({
    queryKey: [identity, 'documents'],
    queryFn: ({ signal }) => api.documents(signal),
    refetchInterval: (state) =>
      state.state.data?.items.some((doc) =>
        ['processing', 'pending', 'queued', 'running', 'deleting'].includes(doc.status),
      )
        ? 3000
        : false,
    refetchIntervalInBackground: false,
  })
  const reload = () => {
    void query.refetch()
  }
  const reindex = useMutation({
    mutationFn: (docId: string) => api.reindex(docId, profiles[docId] || 'legacy-char-v1'),
    onSuccess: reload,
  })
  const deletion = useMutation({
    mutationFn: (docId: string) => api.deleteDocument(docId),
    onSuccess: () => {
      setRemove(null)
      reload()
    },
  })
  const items = query.data?.items || []
  const visible = items.filter((doc) =>
    doc.file_name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  )
  return (
    <div className="knowledge-page">
      <PageHeading
        title="我的资料"
        description="管理原始资料、章节与版本，让提问和练习有据可查。"
        action={
          <span className="quota-counter">
            <FolderOpen size={18} />
            {items.length} <span>/ 10 份资料</span>
          </span>
        }
      />
      <section
        className={`knowledge-upload ${items.length ? 'is-compact' : 'is-empty'}`}
        aria-label="上传学习资料"
      >
        <DocumentUpload onUploaded={reload} disabled={items.length >= 10} />
      </section>
      <section className="knowledge-library" aria-label="资料库">
        <div className="knowledge-toolbar">
          <h2>
            全部资料{' '}
            <span>{search.trim() ? `${visible.length} / ${items.length}` : items.length}</span>
          </h2>
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="搜索资料"
              placeholder="搜索资料名称"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <button
            className="icon-button"
            aria-label="刷新资料"
            disabled={query.isFetching}
            onClick={reload}
          >
            <RefreshCw size={17} />
          </button>
        </div>
        <ErrorNotice error={query.error} onRetry={reload} />
        <ErrorNotice error={reindex.error} />
        {query.isPending ? (
          <Loading />
        ) : visible.length ? (
          <div className="document-list">
            {visible.map((doc) => (
              <article className="document-row" key={doc.doc_id} aria-label={doc.file_name}>
                <span className={`file-icon file-${doc.file_type}`} aria-hidden="true">
                  <FileText size={22} />
                  <span>{doc.file_type.toUpperCase()}</span>
                </span>
                <div className="document-identity">
                  <h2>{doc.file_name}</h2>
                  <p className="document-meta">
                    <span>{formatBytes(doc.file_size)}</span>
                    <span>上传于 {formatDate(doc.created_at)}</span>
                  </p>
                  {doc.error_message && <p className="document-error">{doc.error_message}</p>}
                </div>
                <div className="document-status">
                  <StatusBadge status={doc.status} />
                </div>
                <details className="document-details">
                  <summary>章节与版本</summary>
                  {doc.active_version_id && (
                    <p>
                      当前版本：<code>{doc.active_version_id}</code>
                    </p>
                  )}
                  {doc.sections?.length ? (
                    <ul>
                      {doc.sections.map((section) => (
                        <li key={section.section_id}>{section.title}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>处理完成后，章节目录会显示在这里。</p>
                  )}
                  <label>
                    处理方式
                    <select
                      value={profiles[doc.doc_id] || 'legacy-char-v1'}
                      onChange={(event) =>
                        setProfiles((current) => ({
                          ...current,
                          [doc.doc_id]:
                            event.target.value === 'structure-v1'
                              ? 'structure-v1'
                              : 'legacy-char-v1',
                        }))
                      }
                    >
                      <option value="legacy-char-v1">标准分段</option>
                      <option value="structure-v1">按章节结构</option>
                    </select>
                  </label>
                  <button
                    className="text-button"
                    disabled={
                      reindex.isPending ||
                      ['processing', 'pending', 'deleting'].includes(doc.status)
                    }
                    onClick={() => reindex.mutate(doc.doc_id)}
                  >
                    <RefreshCw size={13} />
                    重新处理
                  </button>
                </details>
                <div className="document-actions">
                  {doc.status === 'ready' && (
                    <Link
                      className="text-button"
                      to={`/qa?doc_id=${encodeURIComponent(doc.doc_id)}`}
                    >
                      向这份资料提问
                    </Link>
                  )}
                  <button
                    className="text-button"
                    onClick={() => setReplace(doc)}
                    disabled={doc.status === 'deleting'}
                  >
                    <Replace size={14} />
                    替换文件
                  </button>
                  <button
                    className="text-button delete-link"
                    aria-label={`删除 ${doc.file_name}`}
                    onClick={() => {
                      deletion.reset()
                      setRemove(doc)
                    }}
                  >
                    <Trash2 size={14} />
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : search.trim() ? (
          <EmptyState
            title="没有找到相关资料"
            action={
              <button className="text-button" onClick={() => setSearch('')}>
                清除搜索
              </button>
            }
          >
            试试其他关键词，或清除搜索查看全部资料。
          </EmptyState>
        ) : !query.error ? (
          <div className="knowledge-empty-note">
            <FolderOpen size={20} aria-hidden="true" />
            <div>
              <h3>从第一份资料开始</h3>
              <p>在上方上传讲义、笔记或工作手册，处理完成后即可提问与练习。</p>
            </div>
          </div>
        ) : null}
      </section>
      <div className="knowledge-note">
        <ShieldCheck size={18} />
        <p>
          这里仅显示你的学习资料。评测资料独立管理；删除或替换后，系统会重新检查题目来源的可用性。
        </p>
      </div>
      {replace && (
        <Dialog title={`替换：${replace.file_name}`} onClose={() => setReplace(null)}>
          <p className="muted tiny">新文件会建立一个新版本，处理成功后生效。</p>
          <DocumentUpload
            docId={replace.doc_id}
            onUploaded={() => {
              setReplace(null)
              reload()
            }}
          />
        </Dialog>
      )}
      {remove && (
        <Dialog title="删除资料" onClose={() => setRemove(null)}>
          <p>确认删除「{remove.file_name}」？</p>
          <p className="muted tiny">删除后，这份资料将无法用于出题，相关历史引用会显示为不可用。</p>
          <ErrorNotice error={deletion.error} />
          <div className="button-row">
            <button className="button secondary" onClick={() => setRemove(null)}>
              保留资料
            </button>
            <button
              className="button danger"
              disabled={deletion.isPending}
              onClick={() => deletion.mutate(remove.doc_id)}
            >
              {deletion.isPending ? '正在删除…' : '确认删除'}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  )
}
