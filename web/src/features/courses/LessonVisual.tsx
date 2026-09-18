import type { ApiSchemas } from '../../types/api'

export type LessonVisual = NonNullable<ApiSchemas['LessonBlock']['visual']>
type VisualStep = ApiSchemas['VisualStep']

/**
 * 安全的教学可视化（B04）。
 *
 * 图形只是可选增强：纯文本由 React 转义渲染，不使用 dangerouslySetInnerHTML、
 * 不加载外部资源；fallback_text 必须可达，图形失效时正文仍然完整可读。
 */
export function LessonVisualView({ visual }: { visual: LessonVisual }) {
  return (
    <figure className="lesson-visual" data-kind={visual.kind}>
      <figcaption>{visual.title}</figcaption>
      {visual.kind === 'comparison' ? (
        <div className="lesson-visual-scroll">
          <table>
            <thead>
              <tr>
                {visual.columns.map((column) => (
                  <th scope="col" key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visual.rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ol className={visual.kind === 'flow' ? 'lesson-visual-flow' : undefined}>
          {visual.steps.map((step: VisualStep, index: number) => (
            <li key={index}>
              <strong>{step.label}</strong>
              {step.detail && <p>{step.detail}</p>}
            </li>
          ))}
        </ol>
      )}
      <details className="lesson-visual-fallback">
        <summary>查看文字说明</summary>
        <p>{visual.fallback_text}</p>
      </details>
    </figure>
  )
}

/** 图形是否存在且结构可渲染；渲染交给 React 文本转义。 */
export function visualIsRenderable(visual: unknown): visual is LessonVisual {
  return (
    !!visual &&
    typeof visual === 'object' &&
    ['flow', 'comparison', 'steps'].includes((visual as { kind?: string }).kind ?? '')
  )
}
