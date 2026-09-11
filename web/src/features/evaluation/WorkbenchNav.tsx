import { Database, FileText, GitCompareArrows, MessageSquare, Play } from 'lucide-react'
import { NavLink } from 'react-router-dom'

export function WorkbenchNav() {
  return (
    <nav className="workbench-nav" aria-label="评测导航">
      <NavLink end to="/evaluations">
        <Database size={16} />
        数据集
      </NavLink>
      <NavLink to="/evaluations/sources">
        <FileText size={16} />
        评测资料
      </NavLink>
      <NavLink to="/evaluations/feedback">
        <MessageSquare size={16} />
        问题反馈
      </NavLink>
      <NavLink to="/evaluations/runs">
        <Play size={16} />
        运行记录
      </NavLink>
      <NavLink to="/evaluations/compare">
        <GitCompareArrows size={16} />
        方案对比
      </NavLink>
    </nav>
  )
}
export function JsonView({ value }: { value: unknown }) {
  return (
    <pre className="json-view">{value == null ? '尚无记录' : JSON.stringify(value, null, 2)}</pre>
  )
}
export function textValue(value: unknown, fallback = '—'): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback
}
export function objectValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}
export function failureCategory(code?: string | null) {
  if (!code) return 'none'
  if (/pars|mapping/i.test(code)) return 'parsing'
  if (/retriev|recall/i.test(code)) return 'retrieval'
  if (/truncat|context_budget/i.test(code)) return 'truncation'
  if (/valid|schema/i.test(code)) return 'validation'
  if (/auth|source|permission|scope/i.test(code)) return 'authorization'
  if (/generat|model_output/i.test(code)) return 'generation'
  return 'infrastructure'
}
export const failureLabels: Record<string, string> = {
  none: '无错误',
  parsing: '解析',
  retrieval: '召回',
  truncation: '截断',
  generation: '生成',
  validation: '验证',
  authorization: '权限或来源',
  infrastructure: '基础设施',
}
