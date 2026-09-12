import { test, expect } from '@playwright/test'
import { installTestApi } from './fixtures'

test('learning pages reflow from 360 to 1440 pixels with long content', async ({
  page,
}, testInfo) => {
  await installTestApi(page, { longName: true })
  for (const width of [360, 390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 960 })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /今天，想学点什么/ })).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth + 1,
    )
    expect(overflow, `unexpected horizontal overflow at ${width}px`).toBe(false)
    if (testInfo.project.name === 'desktop' && [390, 1440].includes(width))
      await page.screenshot({ path: testInfo.outputPath(`home-${width}.png`), fullPage: true })
  }
  await page.goto('/me')
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%'
  })
  await expect(page.getByRole('heading', { name: '学习记录', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  )
})

test('keyboard navigation reaches the goal and the native source drawer closes with Escape', async ({
  page,
}) => {
  await installTestApi(page)
  await page.goto('/')
  await page.getByLabel('学习目标', { exact: true }).focus()
  await page.keyboard.type('集合基础')
  await expect(page.getByLabel('学习目标', { exact: true })).toHaveValue('集合基础')
  await page.goto('/quizzes/quiz-1')
  await page.getByRole('button', { name: '查看来源 1' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: '题目依据' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '查看来源 1' })).toBeFocused()
})
