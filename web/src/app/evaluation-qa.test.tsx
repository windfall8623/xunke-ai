import { screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiFailure, json, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

afterEach(() => vi.unstubAllGlobals())

it('shows QA questions, answer states and citations while preserving unevaluated quality', async () => {
  const sample = {
    sample_id: 'qa-engineering-1', case_type: 'qa', question: '两个资料的结论是否一致？',
    history: [], expected_answer_status: 'conflicting_sources', gold_evidence_groups: [],
    annotation: { status: 'model_draft' },
  }
  const artifact = {
    artifact_type: 'qa', answer_status: 'conflicting_sources',
    blocks: [
      { block_id: 'b1', kind: 'fact', text: '来源甲要求 10 分钟。', citation_refs: ['e1'] },
      { block_id: 'b2', kind: 'fact', text: '来源乙要求 20 分钟。', citation_refs: ['e2'] },
    ], evidence: [], retrieval_query: sample.question,
  }
  renderApp('/evaluations/runs/qa-run', (path) => {
    if (path.endsWith('/auth/session')) return json({ ...session, user: { ...session.user, role: 'evaluator' } })
    if (path.endsWith('/eval/runs/qa-run')) return json({
      run_id: 'qa-run', status: 'completed', comparison_eligible: false,
      progress: { total: 1, completed: 1, failed: 0, pending: 0, scoring: 0 },
      manifest: { repeat_count: 1 }, created_at: '2026-09-09T00:00:00Z',
    })
    if (path.endsWith('/eval/runs/qa-run/results')) return json({ items: [{
      result_id: 'qa-result', sample_id: sample.sample_id, repeat_index: 0, case_type: 'qa',
      status: 'completed', sample, artifact, review: null, review_revision: 0,
      metrics: {
        qa_citation_validity: { status: 'ok', value: 1, unit: 'ratio', denominator: 2 },
        qa_correctness: { status: 'na', value: null, reason: 'not_evaluated', unit: 'ratio' },
      },
    }], total: 1 })
    return apiFailure(404)
  })
  expect(await screen.findByText(sample.question)).toBeVisible()
  expect(screen.getByRole('heading', { name: '问答、引用与校验' })).toBeVisible()
  expect(screen.getByText('回答状态：资料存在冲突')).toBeVisible()
  expect(screen.getByText('引用身份有效率')).toBeVisible()
  expect(screen.getByTestId('qa_citation_validity-value')).toHaveTextContent('100.0%')
  const quality = screen.getByTestId('qa_correctness-value')
  expect(quality).toHaveTextContent('—')
  expect(within(quality.closest('.metric-card') as HTMLElement).getByText('未评估')).toBeVisible()
  expect(screen.queryByText('策略验证样本')).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '题目、引用与校验' })).not.toBeInTheDocument()
})
