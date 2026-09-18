import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GeneratePracticeDialog } from './GeneratePracticeDialog'
import { previewPracticeCost } from '../../services/practice'
import type { PracticeCost } from '../../types/practice'
import type { StudyConcept, StudySpace } from '../../types/study'

vi.mock('../../app/AuthProvider', () => ({ useIdentityKey: () => 7 }))
vi.mock('../../services/practice', () => ({
  previewPracticeCost: vi.fn(),
  generatePractice: vi.fn(),
  practiceErrorMessage: () => '无法预览',
}))
afterEach(() => vi.clearAllMocks())

const preview: PracticeCost = {
  config_source: 'user',
  personal_model_cost_status: 'not_applicable',
  system_cost_status: 'estimated',
  system_cost_cny_upper: '0.012',
  cost_status: 'estimated',
  cost_cny_upper: '0.012',
  generation_llm_call_upper: 4,
  grading_llm_call_upper: 0,
  input_token_upper: 1000,
  output_token_upper: 200,
  embedding_token_upper: 20,
  pricing_version: 'test-prices',
}

function mount() {
  return render(
    <MemoryRouter>
      <GeneratePracticeDialog
        space={{ space_id: 'space-1', title: '集合' } as StudySpace}
        concepts={[{ concept_id: 'concept-1', title: '集合基础', source_status: 'active' } as StudyConcept]}
        scopeRevision={2}
        onClose={() => {}}
      />
    </MemoryRouter>,
  )
}

describe('personal practice cost preview', () => {
  it('separates personal nonbilling from system infrastructure costs and makes no generation call', async () => {
    vi.mocked(previewPracticeCost).mockResolvedValue(preview)
    mount()
    await userEvent.click(screen.getByRole('checkbox', { name: '集合基础' }))
    await userEvent.click(screen.getByRole('button', { name: '查看用量与系统费用上限' }))
    expect(await screen.findByText(/个人模型生成与评分平台不计费/)).toBeVisible()
    expect(screen.getByText(/系统检索服务成本上限 ¥0.0120/)).toBeVisible()
    expect(screen.queryByText(/免费|¥0\.0000/)).not.toBeInTheDocument()
    const { generatePractice } = await import('../../services/practice')
    expect(generatePractice).not.toHaveBeenCalled()
    expect(previewPracticeCost).toHaveBeenCalledWith(
      expect.objectContaining({ space_id: 'space-1', scope_revision: 2 }),
      expect.any(AbortSignal),
    )
  })

  it('keeps missing system prices distinct from personal not-applicable cost', async () => {
    vi.mocked(previewPracticeCost).mockResolvedValue({
      ...preview, system_cost_status: 'unknown', system_cost_cny_upper: null,
      cost_status: 'unknown', cost_cny_upper: null,
    })
    mount()
    await userEvent.click(screen.getByRole('checkbox', { name: '集合基础' }))
    await userEvent.click(screen.getByRole('button', { name: '查看用量与系统费用上限' }))
    expect(await screen.findByText(/系统服务尚有单价未配置/)).toBeVisible()
    expect(screen.getByText(/个人模型生成与评分平台不计费/)).toBeVisible()
    await userEvent.click(screen.getByRole('checkbox', { name: '短解释' }))
    await waitFor(() => expect(screen.queryByText(/系统服务尚有单价未配置/)).not.toBeInTheDocument())
  })
})
