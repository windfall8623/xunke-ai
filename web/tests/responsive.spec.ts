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

test('course reading, saved self checks and summary reflow at 360, 390 and 1440 pixels', async ({ page }, testInfo) => {
  await installTestApi(page, { courses: true, longName: true })
  for (const width of [360, 390, 1440]) {
    await page.setViewportSize({ width, height: 960 })
    await page.goto('/study')
    await page.getByRole('region', { name: '今日学习建议' }).getByRole('link', { name: '继续阅读' }).click()
    await expect(page.getByRole('region', { name: '本课正文' })).toBeVisible()
    const code = page.getByRole('region', { name: '代码示例，可横向滚动' })
    expect(await code.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), `course overflow at ${width}px`).toBe(false)
    const answer = page.getByRole('textbox', { name: /填写你的理解/ })
    await answer.fill(`在 ${width} 像素下保存的自检理解：变量只在定义它的函数中可见。`)
    const check = page.locator('.lesson-check-item').first()
    await check.getByRole('button', { name: '保存回答', exact: true }).click()
    const saved = check.getByRole('button', { name: '回答已保存', exact: true })
    await expect(saved).toBeDisabled()
    expect((await saved.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await page.getByRole('button', { name: '本次先到这里' }).click()
    const summary = page.getByRole('region', { name: '本课小结' })
    await expect(summary.getByText('已保存 1 / 3 题')).toBeVisible()
    await expect(summary.getByText('尚未记录已读')).toBeVisible()
    if (testInfo.project.name === 'desktop' && [360, 1440].includes(width))
      await page.screenshot({ path: testInfo.outputPath(`course-${width}.png`), fullPage: true })
  }
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false)
  await expect(page.getByRole('button', { name: '记录已读，进入本课练习' })).toBeVisible()
})

test('course source keyboard focus survives Escape and a blocked outline preference store', async ({ page }) => {
  await page.addInitScript(() => {
    const getItem = Storage.prototype.getItem
    const setItem = Storage.prototype.setItem
    Storage.prototype.getItem = function (key) {
      if (key === 'xunke.outlineCollapsed') throw new DOMException('blocked', 'SecurityError')
      return getItem.call(this, key)
    }
    Storage.prototype.setItem = function (key, value) {
      if (key === 'xunke.outlineCollapsed') throw new DOMException('blocked', 'SecurityError')
      return setItem.call(this, key, value)
    }
  })
  await installTestApi(page, { courses: true, longName: true })
  await page.setViewportSize({ width: 360, height: 800 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/study/courses/course-1?lesson=lesson-1')
  const outline = page.getByRole('button', { name: '展开课程目录' })
  await expect(outline).toHaveAttribute('aria-expanded', 'false')
  await outline.click()
  const collapse = page.getByRole('button', { name: '收起课程目录' })
  await expect(collapse).toHaveAttribute('aria-expanded', 'true')
  await collapse.click()
  await expect(outline).toBeFocused()
  const source = page.getByRole('button', { name: '查看第 1 段依据 1', exact: true })
  await source.focus()
  await page.keyboard.press('Enter')
  const drawer = page.getByRole('dialog', { name: '课程原文依据' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('变量作用域的已保存资料片段')).toBeVisible()
  expect((await drawer.getByRole('button', { name: '关闭课程原文依据' }).boundingBox())!.height).toBeGreaterThanOrEqual(44)
  expect(await drawer.evaluate(element => element.scrollWidth > element.clientWidth + 1)).toBe(false)
  await page.keyboard.press('Escape')
  await expect(source).toBeFocused()
})
