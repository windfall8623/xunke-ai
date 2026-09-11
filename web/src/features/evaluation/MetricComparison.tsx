import type { Comparison } from '../../types/evaluation'
import { StatusBadge } from '../../components/ui'
import { formatDifference, formatMetric } from './metrics'
import { metricLabel } from './SampleInspector'

export function MetricComparison({ comparison }: { comparison: Comparison }) {
  return (
    <section className="card table-card">
      <div className="comparison-caption">
        <h2>指标与差异</h2>
        <span>
          {comparison.sample_count} 个样本 · {comparison.cluster_count} 个独立簇
        </span>
      </div>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="方案指标对比，可横向滚动"
      >
        <table className="comparison-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>基线</th>
              <th>候选</th>
              <th>差值</th>
              <th>95% 配对区间</th>
              <th>适用样本</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(comparison.metrics || {}).map(([name, row]) => (
              <tr key={name}>
                <th scope="row">
                  {metricLabel[name] || name}
                  <small>{row.unit || row.baseline.unit || '单位未报告'}</small>
                </th>
                <td>{formatMetric(row.baseline)}</td>
                <td>{formatMetric(row.candidate)}</td>
                <td>
                  {row.delta == null ||
                  ['unknown', 'error', 'incomplete', 'na'].includes(row.status || '')
                    ? '—'
                    : formatDifference(
                        { value: 0, unit: row.unit || row.baseline.unit },
                        { value: row.delta, unit: row.unit || row.candidate.unit },
                      )}
                </td>
                <td>
                  {row.confidence_interval
                    ? row.confidence_interval
                        .map((value) =>
                          formatDifference({ value: 0, unit: row.unit }, { value, unit: row.unit }),
                        )
                        .join(' 至 ')
                    : '—'}
                </td>
                <td>{row.sample_count ?? '—'}</td>
                <td>
                  <StatusBadge status={row.status || 'unknown'}>
                    {row.status === 'ok'
                      ? '已有观测'
                      : row.status === 'na'
                        ? '不适用 · NA'
                        : row.status === 'provisional'
                          ? '暂定结果'
                          : row.status === 'incomplete'
                            ? '未完成'
                            : '待裁决'}
                  </StatusBadge>
                  {(row.baseline.reason || row.candidate.reason) && (
                    <small>{row.baseline.reason || row.candidate.reason}</small>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-footnote">
        质量比例显示为百分比，差值显示为百分点。区间以当前冻结的评分协议为条件，不能替代人工校准；单簇或小分组仅供探索。
      </p>
    </section>
  )
}
