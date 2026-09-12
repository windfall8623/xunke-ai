import { useMemo } from 'react'

/**
 * 课文块文本渲染器：把模型生成的纯文本转成可读结构。
 * - ```  围栏内容 → 代码块
 * - 以 SQL/命令关键词开头的整行 → 代码块
 * - 段落中内嵌的语句（如 "……：SELECT ...;"）→ 提取为独立代码块
 * - `反引号` 片段 → 行内代码
 * 其余保持段落与换行。不依赖任何 Markdown 库，对未来接入流式块同样适用。
 */

const CODE_LINE =
  /^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|USE|SHOW|DESCRIBE|DESC|EXPLAIN|WITH|TRUNCATE|REPLACE|GRANT|BEGIN|COMMIT|ROLLBACK|mysql>|pip |npm |python)\b/i
const INLINE_STATEMENT =
  /\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|USE|SHOW|DESCRIBE|DESC|EXPLAIN|WITH|TRUNCATE|REPLACE)\b[^。；;\n]*?[;；]/g

type Segment = { kind: 'prose' | 'code'; text: string }

function segmentsFromProse(text: string): Segment[] {
  const segments: Segment[] = []
  let prose: string[] = []
  let code: string[] = []
  const flushProse = () => {
    const t = prose.join('\n').trim()
    if (t) segments.push({ kind: 'prose', text: t })
    prose = []
  }
  const flushCode = () => {
    const t = code.join('\n').trimEnd()
    if (t) segments.push({ kind: 'code', text: t })
    code = []
  }
  for (const line of text.split('\n')) {
    if (!line.trim()) {
      flushProse()
      flushCode()
      continue
    }
    if (CODE_LINE.test(line)) {
      flushProse()
      code.push(line.replace(/^\s*/, ''))
      continue
    }
    const found: Segment[] = []
    let rest = line
    for (const match of rest.matchAll(INLINE_STATEMENT)) {
      const before = rest.slice(0, match.index)
      if (before.trim()) found.push({ kind: 'prose', text: before.trim() })
      found.push({ kind: 'code', text: match[0].trim() })
      rest = rest.slice((match.index ?? 0) + match[0].length)
    }
    if (found.length) {
      flushProse()
      flushCode()
      segments.push(...found)
      if (rest.trim()) prose.push(rest.trim())
    } else {
      flushCode()
      prose.push(line)
    }
  }
  flushProse()
  flushCode()
  return segments
}

function renderInline(text: string) {
  return text.split(/(`[^`]+`)/g).map((part, i) =>
    part.startsWith('`') && part.endsWith('`') && part.length > 2 ? (
      <code key={i}>{part.slice(1, -1)}</code>
    ) : (
      part
    ),
  )
}

export function LessonText({ text }: { text: string }) {
  const segments = useMemo(() => {
    const normalized = text.replace(/\r\n/g, '\n')
    const out: Segment[] = []
    normalized.split('```').forEach((part, index) => {
      if (index % 2 === 1) {
        const body = part.replace(/^[a-zA-Z0-9_+-]*\n/, '')
        if (body.trim()) out.push({ kind: 'code', text: body.trimEnd() })
      } else {
        out.push(...segmentsFromProse(part))
      }
    })
    return out
  }, [text])
  return (
    <div className="lesson-text">
      {segments.map((segment, index) =>
        segment.kind === 'code' ? (
          <pre className="lesson-code" key={index}>
            <code>{segment.text}</code>
          </pre>
        ) : (
          <p key={index}>{renderInline(segment.text)}</p>
        ),
      )}
    </div>
  )
}
