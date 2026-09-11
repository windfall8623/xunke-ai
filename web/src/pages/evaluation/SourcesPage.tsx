import { useMutation, useQuery } from '@tanstack/react-query'
import { FileSearch, FileText, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import {
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusBadge,
  formatBytes,
} from '../../components/ui'
import { WorkbenchNav } from '../../features/evaluation/WorkbenchNav'
import { DocumentUpload } from '../../features/knowledge/DocumentUpload'
import { evaluationApi } from '../../services/evaluation'
import type { DocumentItem } from '../../types/api'

export function SourcesPage() {
  const identity = useIdentityKey()
  const [selected, setSelected] = useState<DocumentItem | null>(null)
  const [removing, setRemoving] = useState<DocumentItem | null>(null)
  const [profiles, setProfiles] = useState<Record<string, string>>({})
  const query = useQuery({
    queryKey: [identity, 'eval-documents'],
    queryFn: ({ signal }) => evaluationApi.documents(signal),
    refetchInterval: (query) =>
      query.state.data?.items.some((document) =>
        ['processing', 'queued', 'running', 'deleting'].includes(document.status),
      )
        ? 3000
        : false,
    refetchIntervalInBackground: false,
  })
  const refresh = () => {
    void query.refetch()
  }
  const reindex = useMutation({
    mutationFn: (docId: string) =>
      evaluationApi.reindexDocument(docId, profiles[docId] || 'legacy-char-v1'),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (docId: string) => evaluationApi.deleteDocument(docId),
    onSuccess: () => {
      setRemoving(null)
      refresh()
    },
  })
  return (
    <div className="evaluation-page">
      <WorkbenchNav />
      <PageHeading
        title="评测资料"
        description="上传获准用于评测的资料，读取原文、登记来源并建立标注。"
        action={
          <button className="button secondary" onClick={refresh} disabled={query.isFetching}>
            <RefreshCw size={16} />
            刷新
          </button>
        }
      />
      <DocumentUpload
        purpose="evaluation"
        onUploaded={refresh}
        disabled={(query.data?.total || 0) >= 300}
      />
      <p className="tiny muted">评测资料使用独立额度。原文和工件仍受本人权限及授权撤销约束。</p>
      <ErrorNotice error={query.error || reindex.error} onRetry={refresh} />
      {query.isPending ? (
        <Loading />
      ) : !query.data?.items.length ? (
        <section className="card">
          <EmptyState title="还没有评测资料">
            上传资料并等待处理完成后，可查看原文和可登记的来源标识。
          </EmptyState>
        </section>
      ) : (
        <div className="document-grid">
          {query.data.items.map((document) => (
            <article className="card document-card" key={document.doc_id}>
              <div className="document-card-top">
                <span className="icon-tile indigo">
                  <FileText size={22} />
                </span>
                <StatusBadge status={document.status} />
              </div>
              <h2>{document.file_name}</h2>
              <p className="tiny muted">
                {formatBytes(document.file_size)} · {document.file_type.toUpperCase()}
              </p>
              {document.error_message && <p className="document-error">{document.error_message}</p>}
              <button
                className="button secondary button-small"
                disabled={!document.active_build_id}
                onClick={() => setSelected(document)}
              >
                <FileSearch size={16} />
                查看原文与来源标识
              </button>
              <details className="document-details">
                <summary>索引版本与重建</summary>
                <p>
                  当前版本：<code>{document.active_version_id || '处理中'}</code>
                </p>
                <label>
                  索引分块方案
                  <select
                    value={profiles[document.doc_id] || 'legacy-char-v1'}
                    onChange={(event) =>
                      setProfiles((current) => ({
                        ...current,
                        [document.doc_id]: event.target.value,
                      }))
                    }
                  >
                    <option value="legacy-char-v1">字符基线（1000 / 150）</option>
                    <option value="structure-token-v1">结构分块（384 / 64 token）</option>
                  </select>
                </label>
                <button
                  className="text-button"
                  disabled={
                    reindex.isPending ||
                    !document.active_version_id ||
                    ['processing', 'queued', 'running', 'deleting'].includes(document.status)
                  }
                  onClick={() => reindex.mutate(document.doc_id)}
                >
                  <RefreshCw size={14} />
                  构建此方案
                </button>
              </details>
              <div className="document-actions">
                <button
                  className="text-button delete-link"
                  onClick={() => {
                    remove.reset()
                    setRemoving(document)
                  }}
                >
                  <Trash2 size={14} />
                  撤销并删除
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      {selected && <SourceDialog document={selected} onClose={() => setSelected(null)} />}
      {removing && (
        <Dialog title="撤销评测资料" onClose={() => setRemoving(null)}>
          <p>确认撤销「{removing.file_name}」？关联数据集与运行将停止使用其原文。</p>
          <ErrorNotice error={remove.error} />
          <div className="button-row">
            <button className="button secondary" onClick={() => setRemoving(null)}>
              保留资料
            </button>
            <button
              className="button danger"
              disabled={remove.isPending}
              onClick={() => remove.mutate(removing.doc_id)}
            >
              确认撤销
            </button>
          </div>
        </Dialog>
      )}
    </div>
  )
}

function SourceDialog({ document, onClose }: { document: DocumentItem; onClose: () => void }) {
  const identity = useIdentityKey()
  const [block, setBlock] = useState('')
  const [family, setFamily] = useState(document.doc_id)
  const [license, setLicense] = useState('private_owner_authorized')
  const source = useQuery({
    queryKey: [
      identity,
      'eval-source',
      document.doc_id,
      document.active_version_id,
      document.section_catalog_revision,
      block,
    ],
    queryFn: ({ signal }) =>
      evaluationApi.source(
        document.doc_id,
        {
          version_id: document.active_version_id || '',
          parse_artifact_id: document.section_catalog_revision || '',
          ...(block ? { block_id: block } : {}),
        },
        signal,
      ),
    staleTime: 0,
  })
  const value = source.data
  const sourceRef = value
    ? {
        doc_id: value.doc_id,
        source_version_id: value.version_id,
        parse_artifact_id: value.parse_artifact_id,
        canonical_text_hash: value.canonical_text_hash,
        source_sha256: value.source_sha256,
        family_id: family.trim(),
        license,
        authorization_status: 'authorized',
      }
    : null
  return (
    <Dialog title="评测原文与来源标识" className="wide-dialog" onClose={onClose}>
      <h3>{document.file_name}</h3>
      <ErrorNotice
        error={source.error}
        onRetry={() => {
          void source.refetch()
        }}
      />
      {source.isPending ? (
        <Loading />
      ) : source.error ? null : (
        value && (
          <div className="stack-form">
            <label>
              原文段落
              <select
                value={block || value.block_id}
                onChange={(event) => setBlock(event.target.value)}
              >
                {(value.blocks || []).map((item, index) => (
                  <option key={item.block_id} value={item.block_id}>
                    第 {index + 1} 段 · [{item.start_char}, {item.end_char})
                    {item.page ? ` · 第 ${item.page} 页` : ''}
                  </option>
                ))}
              </select>
            </label>
            <div className="evidence-quote">
              <p>{value.excerpt}</p>
            </div>
            <p className="tiny muted">
              block_id：<code>{value.block_id}</code> · 字符范围 [{String(value.locator.start_char)}
              , {String(value.locator.end_char)})
            </p>
            <label>
              文档家族标识
              <input
                value={family}
                maxLength={200}
                onChange={(event) => setFamily(event.target.value)}
              />
            </label>
            <p className="tiny muted">
              同一教材、修订版、翻译或近似重复资料应共用家族标识；相关样本不得跨 split。
            </p>
            <label>
              资料使用许可
              <select value={license} onChange={(event) => setLicense(event.target.value)}>
                <option value="private_owner_authorized">本人获准在私有评测中使用</option>
                <option value="self_created">自建内容</option>
                <option value="public_domain">公有领域</option>
                <option value="CC-BY-4.0">CC BY 4.0（已核对）</option>
              </select>
            </label>
            {value.source_sha256 ? (
              <label>
                可登记的来源 JSON
                <textarea
                  readOnly
                  spellCheck={false}
                  className="code-input"
                  rows={10}
                  value={JSON.stringify(sourceRef, null, 2)}
                  onFocus={(event) => event.target.select()}
                />
              </label>
            ) : (
              <p className="notice warning">服务未返回原文件校验和，暂不能登记完整评测来源。</p>
            )}
            <p className="tiny muted">
              将该来源加入 Manifest 的 sources 与对应样本的 source_refs，再到数据集页填写问题与
              Gold。原文片段和标签仍需人工核对。
            </p>
          </div>
        )
      )}
    </Dialog>
  )
}
