import { test, expect } from '@playwright/test'
import { installTestApi } from './fixtures'

test('answers survive review and reload and completion is never repeated by the report', async ({
  page,
}) => {
  const state = await installTestApi(page)
  await page.goto('/quizzes/quiz-1')
  await page.getByRole('radio', { name: /只保留一个/ }).check()
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
  await expect(page.getByText('回答正确', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '下一题', exact: true }).click()
  await page.getByRole('radio', { name: /是任意集合的子集/ }).check()
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
  await expect(page.getByTestId('answered-count')).toHaveText('2')
  await page.getByRole('button', { name: '上一题', exact: true }).click()
  await expect(page.getByRole('radio', { name: /只保留一个/ })).toBeDisabled()
  await page.reload()
  await expect(page.getByTestId('answered-count')).toHaveText('2')
  await page.getByRole('checkbox', { name: /并集/ }).check()
  await page.getByRole('checkbox', { name: /交集/ }).check()
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
  await page.getByRole('button', { name: '完成练习，查看报告' }).click()
  await expect(page.getByText('+16', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '重试生成分析' })).toBeVisible()
  await page.reload()
  await expect(page.getByText('100%', { exact: true })).toBeVisible()
  expect(state.answers.length).toBe(3)
  expect(state.answerRequests).toBe(3)
  expect(state.completeRequests).toBe(1)
  expect(state.mutationHeaders.every((headers) => headers['x-csrf-token'] === 'browser-csrf')).toBe(
    true,
  )
})

test('selected document generation sends strict scope and task refresh only uses IDs', async ({
  page,
}) => {
  const state = await installTestApi(page)
  state.taskStatus = 'running'
  await page.goto('/')
  await page.getByLabel('学习目标', { exact: true }).fill('掌握集合的核心概念')
  await page.getByRole('radio', { name: /根据我的资料/ }).check()
  await page.getByRole('checkbox', { name: /离散数学/ }).check()
  await page.getByRole('checkbox', { name: '第一节 集合基础', exact: true }).check()
  await page.getByRole('button', { name: '生成练习', exact: true }).click()
  await expect(page).toHaveURL(/\/tasks\/task-1$/)
  await page.reload()
  await expect(page.getByText('正在查找相关依据')).toBeVisible()
  expect(state.generationRequests[0]).toMatchObject({
    source_policy: 'strict_docs',
    scope: {
      type: 'selected_documents',
      documents: [
        { doc_id: 'doc-1', section_catalog_revision: 'parse-1', section_ids: ['section-1'] },
      ],
    },
  })
  expect(state.mutationHeaders[0]['idempotency-key']).toBeTruthy()
})

test('evidence drawer shows saved source safely and supports Escape', async ({ page }) => {
  await installTestApi(page)
  await page.goto('/quizzes/quiz-1')
  await page.getByRole('button', { name: '查看来源 1' }).click()
  const drawer = page.getByRole('dialog', { name: '题目依据' })
  await expect(drawer.getByText('第 2 页')).toBeVisible()
  await expect(
    drawer.getByText('集合中的元素具有互异性。<script>window.evidenceExecuted=true</script>'),
  ).toBeVisible()
  expect(
    await page.evaluate(() => (window as unknown as Record<string, unknown>).evidenceExecuted),
  ).toBeUndefined()
  await page.keyboard.press('Escape')
  await expect(drawer).not.toBeVisible()
})

test('an answer saved before a lost response is retried with the original immutable payload', async ({
  page,
}) => {
  const state = await installTestApi(page)
  const sent: unknown[] = []
  await page.route('**/api/v1/quiz/quiz-1/answers/q1', async (route) => {
    const body = route.request().postDataJSON()
    sent.push(body)
    if (sent.length === 1) {
      state.answers.push({
        ...body,
        question_id: 'q1',
        is_correct: true,
        correct_answers: ['A'],
        explanation: '原文依据',
        citation_refs: ['e1'],
      })
      state.revision++
      return route.abort('failed')
    }
    return route.fallback()
  })
  await page.goto('/quizzes/quiz-1')
  await page.getByRole('radio', { name: /只保留一个/ }).check()
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('网络连接中断')
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
  await expect(page.getByTestId('answered-count')).toHaveText('1')
  expect(sent).toHaveLength(2)
  expect(sent[1]).toEqual(sent[0])
  expect(state.answers).toHaveLength(1)
})

test('image progress continues after the base quiz and exposes partial failures', async ({
  page,
}) => {
  const state = await installTestApi(page)
  state.imagesStatus = 'running'
  await page.goto('/quizzes/quiz-1')
  await expect(page.getByText('配图仍在准备中，你可以先完成练习。')).toBeVisible()
  state.imagesStatus = 'partial'
  await expect(page.getByText('部分配图未完成，不影响答题与报告。')).toBeVisible({
    timeout: 10_000,
  })
  expect(state.quizReads).toBeGreaterThan(1)
  await expect(page.getByRole('radio', { name: /只保留一个/ })).toBeEnabled()
})
