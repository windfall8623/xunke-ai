import { useEffect, useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { formatDate } from '../../components/ui'
import { getRevision, lessonVersion, lessonVersions } from '../../services/courseRevisions'

/**
 * 版本历史（B06）：只读回看旧版正文；旧题不给当前目标补分。
 */
export function CourseVersionHistory({
  courseId,
  lessonId,
  revisionId = null,
  onClose,
}: {
  courseId: string
  lessonId: string
  revisionId?: string | null
  onClose: () => void
}) {
  const [versions, setVersions] = useState<Array<{ content_version: number; archived_at: string; read_at: string | null }> | null>(null)
  const [openVersion, setOpenVersion] = useState<number | null>(null)
  const [content, setContent] = useState<string | null>(null)
  const [revisionStatus, setRevisionStatus] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    lessonVersions(courseId, lessonId)
      .then((items) => {
        if (active) setVersions(items)
      })
      .catch(() => {
        if (active) setVersions([])
      })
    if (revisionId) {
      getRevision(courseId, revisionId)
        .then((view) => {
          if (active) setRevisionStatus(view.status)
        })
        .catch(() => {})
    }
    return () => {
      active = false
    }
  }, [courseId, lessonId, revisionId])

  async function open(contentVersion: number) {
    setOpenVersion(contentVersion)
    setContent(null)
    try {
      const view = await lessonVersion(courseId, lessonId, contentVersion)
      setContent(
        (view.content?.payload?.blocks ?? [])
          .map((block) => block.text)
          .join('\n\n') || '（该版本暂无可展示正文）',
      )
    } catch {
      setContent('旧版本内容读取失败，请稍后重试。')
    }
  }

  return (
    <Dialog title="版本历史" onClose={onClose} className="course-version-history">
      {revisionStatus && (
        <p className="tiny muted">当前修订状态：{{
          preview: '影响预览已生成',
          generating: '候选稿生成中',
          ready: '候选稿已就绪，待确认发布',
          failed: '候选稿生成失败（旧正文未受影响）',
          cancelled: '已取消',
          applied: '已发布新版本',
        }[revisionStatus as 'applied'] ?? revisionStatus}</p>
      )}
      {versions === null ? (
        <p className="tiny muted">正在读取版本列表…</p>
      ) : versions.length === 0 ? (
        <p className="tiny muted">这节课还没有历史版本；修订发布后可在这里回看。</p>
      ) : (
        <ul className="course-version-list">
          {versions.map((item) => (
            <li key={item.content_version}>
              <button
                type="button"
                className={`text-button ${openVersion === item.content_version ? 'selected' : ''}`}
                onClick={() => void open(item.content_version)}
              >
                v{item.content_version} · {formatDate(item.archived_at)}
              </button>
              {openVersion === item.content_version && (
                <pre className="course-version-content">{content ?? '正在读取…'}</pre>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="tiny muted">历史版本只读；旧版回答与成绩保留在原版本，不给当前目标补分。</p>
    </Dialog>
  )
}
