import { test, expect } from '@playwright/test'
import { installTestApi } from './fixtures'
import type { FeedbackView } from '../src/types/evaluation'

test('unknown scores remain unknown and human review is persisted with revision', async ({
  page,
}) => {
  const state = await installTestApi(page, { evaluator: true })
  await page.goto('/evaluations/runs/run-1')
  await expect(page.getByTestId('faithfulness-value')).toHaveText('—')
  await expect(page.getByText('评分待裁决').first()).toBeVisible()
  await expect(page.getByTestId('release-status')).not.toHaveText('已证实改善')
  await page.getByRole('combobox', { name: '人工判定', exact: true }).selectOption('uncertain')
  await page
    .getByLabel('复核理由', { exact: true })
    .fill('评分器尚未返回有效观测，需要补充人工裁决。')
  await page.getByRole('button', { name: '保存复核', exact: true }).click()
  await expect(page.getByText('人工复核已保存')).toBeVisible()
  expect(state.result.review).toMatchObject({ expected_revision: 0, verdict: 'uncertain' })
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '授权导出' }).click()
  expect((await download).suggestedFilename()).toBe('evaluation.jsonl')
})

test('dataset new-version review and explicit freeze then create a bounded run', async ({
  page,
}) => {
  const state = await installTestApi(page, { admin: true })
  await page.goto('/evaluations/datasets/data-1/versions/1')
  await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0)
  await page.getByRole('button', { name: '创建新版本' }).click()
  await expect(page).toHaveURL(/\/versions\/2$/)
  await page
    .getByLabel('标注复核理由', { exact: true })
    .fill('已核对原文片段、问题可回答性与 split。')
  await page.getByRole('button', { name: '记录人工确认' }).click()
  await expect.poll(() => state.datasetReviews.length).toBe(1)
  await expect(page.getByText('版本 2 · revision 2')).toBeVisible()
  const freeze = page.getByRole('button', { name: '验证并冻结' })
  await expect(freeze).toBeDisabled()
  for (const label of [
    '来源授权与许可已核对',
    '原文范围与 hash 已核对',
    '文档家族与 split 已核对',
    '可回答性与请求题量已核对',
    '独立复核覆盖与限制已核对',
  ])
    await page.getByRole('checkbox', { name: label, exact: true }).check()
  await freeze.click()
  await expect(page.getByText('冻结版本保持只读。修改标签或来源时，请创建新版本。')).toBeVisible()
  await page.goto('/evaluations/runs')
  await page.getByRole('combobox', { name: '数据集版本', exact: true }).selectOption('data-1:2')
  await page.getByRole('combobox', { name: '评测方案', exact: true }).selectOption('dense-v1')
  await expect(page.getByText('首轮情景 ¥ 0.001 · 含重试情景 ¥ 0.002')).toBeVisible()
  expect(state.runs).toHaveLength(2)
  await page.getByRole('button', { name: '创建运行', exact: true }).click()
  await expect(page).toHaveURL(/\/evaluations\/runs\/run-3$/)
  await expect(page.getByRole('button', { name: '取消运行' })).toBeVisible()
  await page.getByRole('button', { name: '取消运行' }).click()
  await expect(page.getByRole('button', { name: '恢复运行' })).toBeVisible()
})

test('comparison presents percentage points, intervals and an explicit exploratory status', async ({
  page,
}) => {
  await installTestApi(page, { evaluator: true })
  await page.goto('/evaluations/compare')
  await page.getByRole('combobox', { name: '基线运行', exact: true }).selectOption('run-1')
  await page.getByRole('combobox', { name: '候选运行', exact: true }).selectOption('run-2')
  await page.getByRole('button', { name: '对比运行' }).click()
  await expect(page.getByTestId('release-status')).toHaveText('探索性对照')
  await expect(page.getByRole('cell', { name: '+5.0 个百分点', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '-2.0 个百分点 至 +12.0 个百分点' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  expect(overflow).toBe(false)
})

test('evaluation sources and original spans remain separate from production documents', async ({
  page,
}) => {
  const state = await installTestApi(page, { admin: true })
  await page.goto('/evaluations/sources')
  await page.getByRole('button', { name: '查看原文与来源标识' }).click()
  await expect(page.getByLabel('可登记的来源 JSON')).toContainText('original-hash')
  await page.keyboard.press('Escape')
  await page.getByLabel('选择评测资料文件').setInputFiles({
    name: '评测笔记.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('集合基础'),
  })
  await expect(page.getByRole('heading', { name: '评测笔记.txt' })).toBeVisible()
  expect(state.documents).toHaveLength(1)
  expect(state.evalDocuments).toHaveLength(2)
  state.datasets[0].status = 'draft'
  state.datasets[0].samples[0].source_refs = [
    { doc_id: 'eval-doc-1', source_version_id: 'version-1', parse_artifact_id: 'parse-1' },
  ]
  await page.goto('/evaluations/datasets/data-1/versions/1')
  await page.getByRole('button', { name: '加载原文段落目录' }).click()
  await expect(page.getByLabel('结束字符', { exact: true })).toHaveValue('12')
  await page.getByRole('button', { name: '读取授权原文' }).click()
  await expect(page.getByText('集合的元素具有互异性。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '添加为必要证据组' }).click()
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect.poll(() => state.datasets[0].samples[0].gold_evidence_groups.length).toBe(1)
})

test('evaluators keep history and review access without system execution controls', async ({ page }) => {
  const state = await installTestApi(page, { evaluator: true })
  await page.goto('/evaluations/runs')
  await expect(page.getByRole('button', { name: '创建运行', exact: true })).toBeDisabled()
  await expect(page.getByText(/创建或恢复使用系统模型的评测运行需要管理员权限/)).toBeVisible()
  state.runs[0].status = 'cancelled'
  await page.goto('/evaluations/runs/run-1')
  await expect(page.getByRole('button', { name: '恢复运行' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '授权导出' })).toBeVisible()
  await page.goto('/evaluations/sources')
  await expect(page.getByLabel('选择评测资料文件')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '查看原文与来源标识' })).toBeVisible()
})

test('revoked export displays an error without downloading a response body', async ({ page }) => {
  await installTestApi(page, { evaluator: true })
  await page.route('**/api/v1/eval/runs/run-1/export?*', (route) =>
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ code: 4040, message: '来源授权已撤销', data: null }),
    }),
  )
  const downloads: unknown[] = []
  page.on('download', (download) => downloads.push(download))
  await page.goto('/evaluations/runs/run-1')
  await page.getByRole('button', { name: '授权导出' }).click()
  await expect(page.getByRole('alert')).toContainText('来源授权已撤销')
  expect(downloads).toHaveLength(0)
})

test('authorized feedback becomes a draft candidate after review and preparation survives reload', async ({
  page,
}) => {
  await installTestApi(page, { admin: true })
  let feedback: FeedbackView = {
    feedback_id: 'feedback-1',
    quiz_id: 'quiz-1',
    question_id: 'q1',
    reason: 'citation_mismatch',
    comment: '引用段落未支持此题的答案。',
    allow_evaluation_use: true,
    status: 'pending',
    revision: 1,
    created_at: '2026-09-07T10:00:00Z',
    review: null,
    promotion: null,
    access_scope: 'owner_only',
  }
  const promotionRequests: Record<string, unknown>[] = []
  await page.route(/\/api\/v1\/eval\/feedback(?:\/.*)?$/, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const data = request.method() === 'GET' ? {} : request.postDataJSON()
    const respond = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, message: 'ok', data: body }),
      })
    if (path.endsWith('/review')) {
      expect(data).toEqual({
        expected_revision: 1,
        verdict: 'approved',
        comment: '已核对原题、引用及使用授权。',
      })
      feedback = {
        ...feedback,
        status: 'approved',
        revision: 2,
        review: {
          verdict: 'approved',
          comment: data.comment,
          reviewer_id: 1,
          reviewed_at: '2026-09-07T10:01:00Z',
        },
      }
      return respond(feedback)
    }
    if (path.endsWith('/promote')) {
      promotionRequests.push(data)
      const { expected_revision, ...parameters } = data
      expect(expected_revision).toBe(2)
      if (promotionRequests.length === 1) {
        feedback = {
          ...feedback,
          status: 'preparing',
          promotion: { state: 'preparing', request: parameters },
        }
        return respond({ status: 'preparing', feedback, documents: [] }, 202)
      }
      feedback = {
        ...feedback,
        status: 'promoted',
        revision: 3,
        promotion: {
          state: 'promoted',
          request: parameters,
          dataset_id: 'candidate-1',
          dataset_version: 1,
        },
      }
      return respond(
        {
          status: 'promoted',
          feedback,
          documents: [],
          dataset_id: 'candidate-1',
          dataset_version: 1,
        },
        202,
      )
    }
    return respond({ items: [feedback], total: 1 })
  })
  await page.goto('/evaluations/feedback')
  await expect(page.getByRole('button', { name: '建立评测候选' })).toHaveCount(0)
  await page.getByRole('combobox', { name: '反馈判定', exact: true }).selectOption('approved')
  await page.getByLabel('反馈复核理由', { exact: true }).fill('已核对原题、引用及使用授权。')
  await page.getByRole('button', { name: '保存反馈复核' }).click()
  await page.getByLabel('脱敏后的学习目标').fill('检验集合互异性及其原文依据。')
  await page.getByRole('button', { name: '建立评测候选' }).click()
  await expect(page.getByRole('button', { name: '继续建立候选' })).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('脱敏后的学习目标')).toHaveValue('检验集合互异性及其原文依据。')
  await expect(page.getByLabel('脱敏后的学习目标')).toBeDisabled()
  expect(promotionRequests).toHaveLength(1)
  await page.getByRole('button', { name: '继续建立候选' }).click()
  await expect(page.getByText('候选已建立，标签仍需人工核对。')).toBeVisible()
  await expect(page.getByRole('link', { name: '打开候选数据集' })).toHaveAttribute(
    'href',
    '/evaluations/datasets/candidate-1/versions/1',
  )
  expect(promotionRequests).toHaveLength(2)
  expect(promotionRequests[1]).toEqual(promotionRequests[0])
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})
