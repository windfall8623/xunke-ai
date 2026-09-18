import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFailure, json, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

afterEach(() => vi.unstubAllGlobals())

function renderPreview(status: 'estimated' | 'unknown') {
  const queries: URLSearchParams[] = []
  renderApp('/evaluations/runs', (path, init) => {
    if (path.endsWith('/auth/session'))
      return json({ ...session, user: { ...session.user, role: 'evaluator' } })
    if (path.endsWith('/eval/datasets'))
      return json({
        items: [
          {
            dataset_id: 'cost-data',
            version: 1,
            name: '费用集合',
            status: 'frozen',
            revision: 1,
            manifest: {},
            sample_count: 3,
          },
        ],
        total: 1,
      })
    if (path.endsWith('/eval/pipelines'))
      return json({ items: [{ pipeline_id: 'dense-v1', name: '向量检索', config: {} }], total: 1 })
    if (path.endsWith('/eval/judges'))
      return json({
        items: [
          {
            judge_profile_id: 'deterministic-v1',
            name: '人工评分',
            description: '人工复核',
            calibrated: false,
          },
        ],
        total: 1,
      })
    if (path.includes('/eval/runs/estimate?')) {
      expect(init.method).toBe('GET')
      const query = new URL(path, 'http://test').searchParams
      queries.push(query)
      const repeats = Number(query.get('repeat_count'))
      return json({
        status,
        method: 'configured_price_scenarios_v1',
        currency: 'CNY',
        not_a_bill: true,
        pricing_version: 'fixture-prices-v1',
        sample_count: 3,
        repeat_count: repeats,
        planned_executions: 3 * repeats,
        first_attempt_cny: status === 'estimated' ? 0.125 * repeats : null,
        retry_scenario_cny: status === 'estimated' ? 0.5 * repeats : null,
        assumptions: ['按全部重复次数计算；实际调用可能提前停止。'],
        components: [
          {
            stage: 'generation',
            status,
            first_attempt_cny: status === 'estimated' ? 0.125 * repeats : null,
            retry_scenario_cny: status === 'estimated' ? 0.5 * repeats : null,
            first_attempt_calls: 6 * repeats,
            retry_scenario_calls: 15 * repeats,
            missing_prices: status === 'unknown' ? ['llm_output_cny_per_million'] : [],
            assumptions: ['每次调用按 4096 输出 token 估计。'],
            reason: status === 'unknown' ? '缺少输出单价，费用未知。' : null,
          },
          {
            stage: 'indexing',
            status: 'not_applicable',
            first_attempt_cny: null,
            retry_scenario_cny: null,
            first_attempt_calls: 0,
            retry_scenario_calls: 0,
            missing_prices: [],
            assumptions: [],
            reason: '已有索引成本不在本次运行内。',
          },
        ],
      })
    }
    if (path.endsWith('/eval/runs'))
      return json({
        items: [
          {
            run_id: 'prior-run',
            dataset_id: 'cost-data',
            dataset_version: 1,
            pipeline_id: 'dense-v1',
            status: 'completed',
            progress: { total: 3, completed: 3, failed: 0 },
            comparison_eligible: false,
            manifest: {},
            max_cost_cny: 10,
            spent_cny: 0.25,
            reserved_cny: 0.05,
            created_at: '2026-09-08T00:00:00Z',
          },
        ],
        total: 1,
      })
    return apiFailure(404)
  })
  return queries
}

async function selectRun() {
  await userEvent.selectOptions(await screen.findByLabelText('数据集版本'), 'cost-data:1')
  await userEvent.selectOptions(screen.getByLabelText('评测方案'), 'dense-v1')
}

describe('run cost preview', () => {
  it('shows server-priced scenarios, refreshes repeats and separates recorded and reserved costs', async () => {
    const queries = renderPreview('estimated')
    await selectRun()
    expect(await screen.findByText('首轮情景 ¥ 0.125 · 含重试情景 ¥ 0.5')).toBeVisible()
    expect(screen.getByText('已记录 ¥ 0.25')).toBeVisible()
    expect(screen.getByText('预留待结算 ¥ 0.05')).toBeVisible()
    await userEvent.selectOptions(screen.getByLabelText('重复次数'), '2')
    expect(await screen.findByText('首轮情景 ¥ 0.25 · 含重试情景 ¥ 1')).toBeVisible()
    expect(queries.at(-1)?.get('repeat_count')).toBe('2')
    expect(queries.every((query) => !query.has('max_cost_cny'))).toBe(true)
    await userEvent.click(screen.getByText('费用依据与用量假设'))
    expect(screen.getByText('每次调用按 4096 输出 token 估计。')).toBeVisible()
  })

  it('shows missing prices as unknown and never substitutes the budget', async () => {
    renderPreview('unknown')
    await selectRun()
    expect(await screen.findByText('暂无法估算费用')).toBeVisible()
    expect(screen.queryByText(/首轮情景 ¥/)).not.toBeInTheDocument()
    expect(screen.getByText('预算上限 ¥ 10.00')).toBeVisible()
    await userEvent.click(screen.getByText('费用依据与用量假设'))
    expect(screen.getByText('缺少输出单价，费用未知。')).toBeVisible()
    expect(screen.getByText('索引：不适用')).toBeVisible()
    expect(screen.getByRole('button', { name: '创建运行' })).toBeDisabled()
  })
})
