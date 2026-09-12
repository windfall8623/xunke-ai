import { expect, test } from '@playwright/test'
import { qaAnswer, qaDocument, qaEvidence, qaMessages } from '../src/test/qaFixtures'
import { installQaApi } from './qaFixtures'

test('creates from ready material, restores a queued answer after reload, reads a citation, follows up and cancels', async ({
  page,
}, testInfo) => {
  const state = await installQaApi(page, { existing: false, completed: false })
  await page.goto('/knowledge')
  await page.getByRole('link', { name: '向这份资料提问' }).click()
  await expect(page.getByRole('checkbox', { name: qaDocument.file_name })).toBeChecked()
  await page.getByRole('checkbox', { name: '第一节 集合基础' }).check()
  await page.getByLabel('会话标题（选填）').fill('集合问答')
  await page.getByRole('button', { name: '创建会话' }).click()
  await expect(page).toHaveURL(/\/qa\/session-1$/)
  await page.getByLabel('你的问题').fill('集合中重复元素如何处理？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByText('正在排队', { exact: true })).toBeVisible()
  expect(state.pendingTaskId).toBe('qa-task-1')
  await page.reload()
  await expect(page.getByText('正在排队', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '发送问题' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '更改范围' })).toBeDisabled()
  state.complete('qa-task-1')
  await expect(page.getByText(qaAnswer.blocks[0].text, { exact: true })).toBeVisible()
  expect(state.submissions).toHaveLength(1)
  const citation = page.getByRole('button', { name: /查看引用 1/ })
  await citation.click()
  const drawer = page.getByRole('dialog', { name: '引用原文' })
  await expect(drawer.getByText(qaEvidence.excerpt)).toBeVisible()
  await expect(drawer.getByText('第一章 / 第一节 集合基础')).toBeVisible()
  await expect(drawer.getByText('第 2 页')).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: testInfo.outputPath('qa-evidence.png') })
  await page.keyboard.press('Escape')
  await expect(citation).toBeFocused()
  await page.getByRole('button', { name: '有帮助', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /允许将本轮问答用于评测改进/ })).not.toBeChecked()
  await page.getByRole('button', { name: '提交反馈' }).click()
  await expect(page.getByText('反馈已保存')).toBeVisible()
  expect(state.feedback[0].evaluation_consent).toBe(false)
  await page.getByLabel('你的问题').fill('那空集呢？')
  await page.getByLabel('你的问题').press('Enter')
  await expect(page.getByText('正在排队', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '取消回答' }).click()
  await expect(page.getByText('已取消本次回答', { exact: true })).toBeVisible()
  await expect(page.getByText(qaAnswer.blocks[0].text, { exact: true })).toBeVisible()
  expect(state.submissions).toHaveLength(2)
  expect(state.submissions[0].key).not.toBe(state.submissions[1].key)
  expect(
    state.base.mutationHeaders.every((headers) => headers['x-csrf-token'] === 'browser-csrf'),
  ).toBe(true)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: testInfo.outputPath('qa-conversation.png'), fullPage: true })
})

test('discards already loaded text and source drawer when scope authorization is revoked', async ({
  page,
}) => {
  const state = await installQaApi(page)
  await page.goto('/qa/session-1')
  await page.getByRole('button', { name: /查看引用 1/ }).click()
  await expect(page.getByText(qaEvidence.excerpt)).toBeVisible()
  state.revoked = true
  await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
  await expect(page.getByText(qaAnswer.blocks[0].text, { exact: true })).toHaveCount(0)
  await expect(page.getByText(qaMessages[0].content, { exact: true })).toHaveCount(0)
  await expect(page.getByText(qaEvidence.excerpt)).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: '引用原文' })).toHaveCount(0)
  await expect(page.getByLabel('你的问题')).toBeDisabled()
  await page.getByRole('button', { name: '更改范围' }).click()
  await page.getByRole('checkbox', { name: qaDocument.file_name }).check()
  await page.getByRole('button', { name: '保存范围' }).click()
  await expect(page.getByLabel('你的问题')).toBeEnabled()
})

test('recovers an uncertain submit with the same key across reload and explicitly retries failed work with a new key', async ({
  page,
}) => {
  const state = await installQaApi(page)
  state.abortNextSubmit = true
  state.failTasks = true
  await page.goto('/qa/session-1')
  await page.getByLabel('你的问题').fill('重复元素为什么只计一次？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByText(/提交结果尚未确认/)).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '重试确认提交' }).click()
  await expect(page.getByText('回答服务暂不可用', { exact: true })).toBeVisible()
  expect(state.submissions).toHaveLength(2)
  expect(state.submissions[1]).toEqual(state.submissions[0])
  await page.getByRole('button', { name: '重试这个问题' }).click()
  await expect.poll(() => state.submissions.length).toBe(3)
  expect(state.submissions[2].key).not.toBe(state.submissions[0].key)
  expect(state.submissions[2].data).toEqual(state.submissions[0].data)
  await expect(page.getByText('资料不足', { exact: true })).toHaveCount(0)
})

test('handles a concurrent scope revision before accepting the next explicit save', async ({
  page,
}) => {
  const state = await installQaApi(page)
  state.scopeConflicts = 1
  await page.goto('/qa/session-1')
  await page.getByRole('button', { name: '更改范围' }).click()
  const dialog = page.getByRole('dialog', { name: '更改问答范围' })
  await dialog.getByRole('button', { name: '保存范围' }).click()
  await expect(dialog.getByText('范围已由另一页面更新，请重新确认')).toBeVisible()
  await expect(dialog.getByText(/范围版本 2/)).toBeVisible()
  await dialog.getByRole('button', { name: '保存范围' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('范围版本 3', { exact: true })).toBeVisible()
  expect(state.scopeUpdates.map((request) => request.expected_revision)).toEqual([1, 2])
})

test('keeps long answers and canonical source text inside desktop and phone viewports', async ({
  page,
}, testInfo) => {
  await installQaApi(page, { longContent: true })
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 920 })
    await page.goto('/qa/session-1')
    await expect(page.getByText('回答完成', { exact: true })).toBeVisible()
    if (width > 900) await expect(page.getByRole('button', { name: '会话列表' })).toBeHidden()
    await expect(page.locator('img[src="x"]')).toHaveCount(0)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
      `page overflow at ${width}px`,
    ).toBe(false)
    await page.getByRole('button', { name: /查看引用 1/ }).click()
    const dialog = page.getByRole('dialog', { name: '引用原文' })
    await expect(dialog.getByText(/CanonicalSourceText/)).toBeVisible()
    const bounds = await dialog.boundingBox()
    expect(bounds?.height).toBe(920)
    if (width <= 767) expect(bounds?.width).toBe(width)
    expect(
      await dialog.evaluate((node) => node.scrollWidth > node.clientWidth + 1),
      `source overflow at ${width}px`,
    ).toBe(false)
    await page.keyboard.press('Escape')
  }
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: testInfo.outputPath('qa-long-content.png'), fullPage: true })
})

test('clears private QA content and redirects to login when the session expires', async ({
  page,
}) => {
  const state = await installQaApi(page)
  await page.goto('/qa/session-1')
  await expect(page.getByText(qaAnswer.blocks[0].text, { exact: true })).toBeVisible()
  state.base.authenticated = false
  await page.getByRole('button', { name: '刷新会话' }).click()
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await expect(page.getByText(qaAnswer.blocks[0].text, { exact: true })).toHaveCount(0)
  await expect(page).toHaveURL(/\/login$/)
})
