import { test, expect } from '@playwright/test'
import { installTestApi } from './fixtures'

test('uploads a browser file, restores status, and removes a document with source invalidation', async ({
  page,
}) => {
  await installTestApi(page)
  await page.goto('/knowledge')
  await page.getByLabel('选择资料文件', { exact: true }).setInputFiles({
    name: '第二章.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('这一章介绍关系与函数。'),
  })
  await expect(page.getByRole('heading', { name: '第二章.txt', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('正在处理', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '删除 离散数学 · 第一章.pdf', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '离散数学 · 第一章.pdf', exact: true }),
  ).toHaveCount(0)
  await page.goto('/quizzes/quiz-1')
  await page.getByRole('button', { name: '查看来源 1' }).click()
  await expect(page.getByRole('heading', { name: '来源暂不可用' })).toBeVisible()
})
