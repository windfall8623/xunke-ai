import { ShieldCheck } from 'lucide-react'

/**
 * 循证状态条：把课程/课时的多条诚实说明（未核验、版本敏感、使用边界）
 * 收敛为一行可展开的摘要，避免"免责声明墙"稀释信任感。
 */
export function EvidenceNoticeBar({ warnings }: { warnings: string[] }) {
  if (!warnings?.length) return null
  const head = warnings[0].split(/[。；;]/)[0]
  const short = head.length > 46 ? `${head.slice(0, 46)}…` : head
  return (
    <details className="evidence-bar">
      <summary>
        <ShieldCheck size={15} />
        <span className="evidence-bar-summary">{short}</span>
        <span className="evidence-bar-count">
          {warnings.length} 条说明 · 点击展开
        </span>
      </summary>
      <ul>
        {warnings.map((warning, index) => (
          <li key={index}>{warning}</li>
        ))}
      </ul>
    </details>
  )
}
