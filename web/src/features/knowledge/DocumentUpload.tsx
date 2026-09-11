import { useMutation } from '@tanstack/react-query'
import { CloudUpload, FileCheck2 } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { api } from '../../services/api'
import { evaluationApi } from '../../services/evaluation'
import { ErrorNotice, Loading } from '../../components/ui'

export function DocumentUpload({
  onUploaded,
  disabled = false,
  docId,
  purpose = 'production',
}: {
  onUploaded: () => void
  disabled?: boolean
  docId?: string
  purpose?: 'production' | 'evaluation'
}) {
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const upload = useMutation({
    mutationFn: (file: File) =>
      purpose === 'evaluation' ? evaluationApi.uploadDocument(file) : api.upload(file, docId),
    onSuccess: () => onUploaded(),
  })
  function selectFile(file?: File) {
    setError('')
    if (!file || disabled || upload.isPending) return
    if (file.size > 10 * 1024 * 1024) {
      setError('单份资料不能超过 10 MB，请拆分或压缩后再上传。')
      return
    }
    if (!/\.(pdf|docx|md|txt)$/i.test(file.name)) {
      setError('请选择 PDF、DOCX、Markdown 或 TXT 格式的资料。')
      return
    }
    if (file.size === 0) {
      setError('文件内容为空，请选择有效资料。')
      return
    }
    upload.mutate(file)
  }
  return (
    <div>
      <div
        className={`upload-zone ${dragging ? 'is-dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (event.dataTransfer.files.length > 1) setError('请一次上传一份资料。')
          else selectFile(event.dataTransfer.files[0])
        }}
      >
        <span className="upload-icon">
          <CloudUpload size={28} />
        </span>
        <div>
          <h2>
            {docId
              ? '选择替换文件'
              : purpose === 'evaluation'
                ? '上传评测专用资料'
                : '把学习资料带进来'}
          </h2>
          <p>拖入文件，或点击上传 · PDF / DOCX / MD / TXT</p>
          <span>
            每份不超过 10 MB
            {docId
              ? ' · 替换后保留版本记录'
              : purpose === 'evaluation'
                ? ' · 使用独立评测额度'
                : ' · 最多 10 份资料'}
          </span>
        </div>
        <input
          ref={input}
          id={id}
          className="sr-only"
          aria-label={
            docId ? '选择替换文件' : purpose === 'evaluation' ? '选择评测资料文件' : '选择资料文件'
          }
          type="file"
          accept=".pdf,.docx,.md,.txt"
          disabled={disabled || upload.isPending}
          onChange={(event) => {
            selectFile(event.target.files?.[0])
            event.target.value = ''
          }}
        />
        <button
          type="button"
          className="button primary"
          disabled={disabled || upload.isPending}
          onClick={() => input.current?.click()}
        >
          <CloudUpload size={17} />
          {upload.isPending ? '正在上传…' : docId ? '选择文件' : '上传资料'}
        </button>
      </div>
      {upload.isPending && <Loading>文件正在上传，处理状态会保存到资料列表。</Loading>}
      {upload.isSuccess && (
        <div className="upload-success" role="status">
          <FileCheck2 size={16} />
          {purpose === 'evaluation'
            ? '上传已收到，处理完成后可用于标注和评测。'
            : '上传已收到，处理完成后即可出题。'}
        </div>
      )}
      <ErrorNotice error={error || upload.error} />
      {disabled && <p className="tiny muted">已达到资料上限，删除不再需要的资料后可继续上传。</p>}
    </div>
  )
}
