import { useEffect, useState } from 'react'
import { request } from '../../services/http'
import type { ApiSchemas } from '../../types/api'

type LearningHabitView = ApiSchemas['LearningHabitView']
type HabitRestPreferences = ApiSchemas['HabitRestPreferences']

const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日']

export function getHabits(signal?: AbortSignal) {
  return request<LearningHabitView>('/study/habits', { signal })
}

export function updateHabitPreferences(
  body: { expected_revision: number; weekly_rest_days: number[] },
  signal?: AbortSignal,
) {
  return request<HabitRestPreferences>('/study/habit-preferences', {
    method: 'PATCH', data: body, signal,
  })
}

/**
 * 有效学习记录（C02）：按已保存的学习活动统计，不代表已掌握；
 * 休息日不增长天数也不制造完成记录。
 */
export function LearningHabitCard() {
  const [habits, setHabits] = useState<LearningHabitView | null>(null)
  const [restDays, setRestDays] = useState<number[]>([])
  const [revision, setRevision] = useState(1)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getHabits()
      .then((view) => {
        if (!active) return
        setHabits(view)
      })
      .catch(() => {
        if (active) setError('学习记录暂未读回。')
      })
    getRestPrefs().then((prefs) => {
      if (!active) return
      setRestDays(prefs.weekly_rest_days ?? [])
      setRevision(prefs.revision ?? 1)
    }).catch(() => {})
    return () => {
      active = false
    }
  }, [])

  async function getRestPrefs() {
    const { request: req } = await import('../../services/http')
    return req<HabitRestPreferences>('/study/habit-preferences')
  }

  async function toggleRest(day: number) {
    const next = restDays.includes(day)
      ? restDays.filter((item) => item !== day)
      : [...restDays, day].sort()
    setRestDays(next)
    try {
      const saved = await updateHabitPreferences({ expected_revision: revision, weekly_rest_days: next })
      setRevision(saved.revision ?? revision + 1)
    } catch {
      setError('休息设置未保存，请稍后重试。')
    }
  }

  if (error && !habits) return null
  if (!habits) return null
  return (
    <section className="card learning-habits" aria-label="有效学习记录">
      <h3>有效学习记录</h3>
      <p>
        连续有效学习 <strong>{habits.effective_streak_days}</strong> 天
        {habits.rest_days_in_streak > 0 && `（期间休息 ${habits.rest_days_in_streak} 天）`}
        ，累计 {habits.effective_days_total} 天。
      </p>
      <p className="tiny muted">按已保存的学习活动统计，不代表已掌握；打开页面不计入。</p>
      <div className="habit-days">
        {(habits.recent_days ?? []).slice(-14).map((day) => (
          <span key={day.local_date} className={`habit-day ${day.kind}`} title={day.local_date} />
        ))}
      </div>
      <div className="habit-rest-picker">
        <span className="tiny muted">每周休息日：</span>
        {weekdayLabels.map((label, index) => (
          <button
            key={label}
            type="button"
            className={`button secondary habit-rest-day ${restDays.includes(index) ? 'selected' : ''}`}
            onClick={() => void toggleRest(index)}
          >
            周{label}
          </button>
        ))}
      </div>
      {error && <p role="alert" className="tiny">{error}</p>}
    </section>
  )
}
