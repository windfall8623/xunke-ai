import { useEffect, useState } from 'react'
import { Dialog } from '../../components/Dialog'
import {
  difficultyLabels,
  getPreferences,
  updatePreferences,
  type LearningPreferencesView,
} from '../../services/studyPreferences'

/**
 * 学习节奏设置：日预算、每日复习量、难度与时区展示。
 * 难度是用户选择而非系统测得能力；调整不改变已结算成绩与目标标准。
 */
export function LearningPreferencesDialog({ onClose }: { onClose: () => void }) {
  const [prefs, setPrefs] = useState<LearningPreferencesView | null>(null)
  const [minutes, setMinutes] = useState(20)
  const [reviewLimit, setReviewLimit] = useState(1)
  const [difficulty, setDifficulty] =
    useState<LearningPreferencesView['difficulty']>('mixed')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    let active = true
    getPreferences()
      .then((view) => {
        if (!active) return
        setPrefs(view)
        setMinutes(view.daily_minutes)
        setReviewLimit(view.daily_review_limit)
        setDifficulty(view.difficulty)
      })
      .catch(() => {
        if (active) setError('学习偏好暂未读回，请稍后重试。')
      })
    return () => {
      active = false
    }
  }, [])

  async function save() {
    if (!prefs || pending) return
    setPending(true)
    setError(null)
    try {
      const view = await updatePreferences({
        expected_revision: prefs.revision,
        daily_minutes: minutes,
        daily_review_limit: reviewLimit,
        difficulty,
        timezone: prefs.timezone,
      })
      setPrefs(view)
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存未完成，请刷新后重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog title="学习节奏设置" onClose={onClose} className="preferences-dialog">
      {prefs ? (
        <form
          className="preferences-form"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <label htmlFor="pref-minutes">每天学习时间（分钟，5–120）</label>
          <input
            id="pref-minutes"
            type="number"
            min={5}
            max={120}
            value={minutes}
            onChange={(event) => setMinutes(Number(event.target.value))}
          />
          <small className="tiny muted">预计用时是安排估计，不代表实际学习耗时。</small>

          <label htmlFor="pref-review-limit">每天新推荐的复习数量（0–3）</label>
          <input
            id="pref-review-limit"
            type="number"
            min={0}
            max={3}
            value={reviewLimit}
            onChange={(event) => setReviewLimit(Number(event.target.value))}
          />
          <small className="tiny muted">
            设为 0 不会删除逾期复习，只是不再主动推荐，可随时手动进入复习。
          </small>

          <fieldset>
            <legend>难度偏好</legend>
            {(Object.keys(difficultyLabels) as Array<LearningPreferencesView['difficulty']>).map(
              (option) => (
                <label key={option}>
                  <input
                    type="radio"
                    name="pref-difficulty"
                    checked={difficulty === option}
                    onChange={() => setDifficulty(option)}
                  />
                  {difficultyLabels[option]}
                </label>
              ),
            )}
          </fieldset>
          <small className="tiny muted">
            难度是你自己的选择，不是系统测得的能力；不会改变课程目标的通过标准或已有成绩。
            时区：{prefs.timezone}（从账号设置读取，暂不在此修改）。
          </small>

          <button type="submit" className="button primary" disabled={pending}>
            {pending ? '正在保存…' : saved ? '已保存' : '保存学习偏好'}
          </button>
          {error && <p role="alert" className="preferences-error">{error}</p>}
        </form>
      ) : (
        <p>{error ?? '正在读取学习偏好…'}</p>
      )}
    </Dialog>
  )
}
