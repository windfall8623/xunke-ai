import { useMutation } from '@tanstack/react-query'
import { FileSearch, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ErrorNotice } from '../../components/ui'
import { evaluationApi } from '../../services/evaluation'
import type { DatasetSample, JsonObject } from '../../types/evaluation'
import { buildGoldSpan } from './dataset'
import { textValue } from './WorkbenchNav'

export function SpanEditor({
  sample,
  onAdd,
}: {
  sample: DatasetSample
  onAdd: (span: JsonObject) => void
}) {
  const sources = sample.source_refs || []
  const [sourceIndex, setSourceIndex] = useState(0)
  const [block, setBlock] = useState('')
  const [start, setStart] = useState('0')
  const [end, setEnd] = useState('')
  const [error, setError] = useState('')
  const source = sources[sourceIndex]
  const sourceCatalog = useMutation({
    mutationFn: () =>
      evaluationApi.source(textValue(source.doc_id, ''), {
        version_id: textValue(source.source_version_id || source.version_id, ''),
        parse_artifact_id: textValue(source.parse_artifact_id, ''),
      }),
    onSuccess: (value) => {
      setBlock(value.block_id)
      setStart(String(value.locator.start_char))
      setEnd(String(value.locator.end_char))
      fetchSource.reset()
    },
  })
  const fetchSource = useMutation({
    mutationFn: () => {
      if (
        !source ||
        !block.trim() ||
        !Number.isInteger(Number(start)) ||
        !Number.isInteger(Number(end)) ||
        Number(start) < 0 ||
        Number(end) <= Number(start)
      )
        throw new Error('请填写有效的 block_id 和左闭右开字符范围。')
      return evaluationApi.source(textValue(source.doc_id, ''), {
        version_id: textValue(source.source_version_id || source.version_id, ''),
        parse_artifact_id: textValue(source.parse_artifact_id, ''),
        block_id: block.trim(),
        start_char: start,
        end_char: end,
      })
    },
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    fetchSource.mutate()
  }
  return (
    <div className="span-editor">
      <h3>原文片段标注</h3>
      <p className="tiny muted">
        从该样本已登记的来源读取片段。偏移采用 Unicode code point 的 [start, end)，定位与 hash
        由服务端返回。
      </p>
      {!source ? (
        <p className="tiny muted">先在样本的 source_refs 中登记授权来源。</p>
      ) : (
        <>
          <form className="stack-form" onSubmit={submit}>
            <label>
              来源引用
              <select
                value={sourceIndex}
                onChange={(event) => {
                  setSourceIndex(Number(event.target.value))
                  fetchSource.reset()
                  sourceCatalog.reset()
                  setBlock('')
                  setStart('0')
                  setEnd('')
                }}
              >
                {sources.map((ref, index) => (
                  <option key={index} value={index}>
                    {textValue(ref.doc_id)} · {textValue(ref.source_version_id || ref.version_id)}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="button secondary button-small"
              disabled={sourceCatalog.isPending}
              onClick={() => sourceCatalog.mutate()}
            >
              {sourceCatalog.isPending ? '正在读取目录…' : '加载原文段落目录'}
            </button>
            {!!sourceCatalog.data?.blocks?.length && (
              <label>
                选择原文段落
                <select
                  value={block}
                  onChange={(event) => {
                    const selected = sourceCatalog.data?.blocks?.find(
                      (item) => item.block_id === event.target.value,
                    )
                    if (!selected) return
                    setBlock(selected.block_id)
                    setStart(String(selected.start_char))
                    setEnd(String(selected.end_char))
                    fetchSource.reset()
                  }}
                >
                  {sourceCatalog.data.blocks.map((item, index) => (
                    <option key={item.block_id} value={item.block_id}>
                      第 {index + 1} 段 · [{item.start_char}, {item.end_char})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="span-fields">
              <label>
                block_id
                <input
                  value={block}
                  onChange={(event) => {
                    setBlock(event.target.value)
                    fetchSource.reset()
                  }}
                  required
                />
              </label>
              <label>
                开始字符
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={start}
                  onChange={(event) => {
                    setStart(event.target.value)
                    fetchSource.reset()
                  }}
                  required
                />
              </label>
              <label>
                结束字符
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={end}
                  onChange={(event) => {
                    setEnd(event.target.value)
                    fetchSource.reset()
                  }}
                  required
                />
              </label>
            </div>
            <button className="button secondary button-small" disabled={fetchSource.isPending}>
              <FileSearch size={16} />
              {fetchSource.isPending ? '正在读取…' : '读取授权原文'}
            </button>
          </form>
          <ErrorNotice error={fetchSource.error || sourceCatalog.error || error} />
          {fetchSource.data && (
            <div className="span-preview">
              <p>{fetchSource.data.excerpt}</p>
              <button
                type="button"
                className="button secondary button-small"
                onClick={() => {
                  try {
                    const span = buildGoldSpan(fetchSource.data!)
                    onAdd(span)
                    fetchSource.reset()
                  } catch (cause) {
                    setError(cause instanceof Error ? cause.message : '定位无效')
                  }
                }}
              >
                <Plus size={15} />
                添加为必要证据组
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
