import { test, expect } from '@playwright/test'
import { installTestApi } from './fixtures'

test('feedback is private by default and review generation cannot override scope', async ({
  page,
}) => {
  const state = await installTestApi(page)
  await page.goto('/quizzes/quiz-1')
  await page.getByRole('button', { name: '反馈题目问题', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /允许用于后续评测/ })).not.toBeChecked()
  await page.getByLabel('补充说明').fill('请核对原文中的定义。')
  await page.getByRole('button', { name: '提交反馈', exact: true }).click()
  await expect(page.getByText('反馈已收到，感谢帮助我们改进。')).toBeVisible()
  expect(state.feedback[0].allow_evaluation_use).toBe(false)
  await page.goto('/quizzes/quiz-1/report')
  await page.getByRole('button', { name: '再练一组', exact: true }).click()
  await expect.poll(() => state.generationRequests.length).toBe(1)
  expect(state.generationRequests[0]).toEqual({
    review_of_quiz_id: 'quiz-1',
    question_count: 3,
    difficulty: 'mixed',
  })
})
