import type { CourseCreate } from '../../types/course'

export type CourseCreateOptionsValue = Pick<
  CourseCreate,
  'goal' | 'prior_knowledge' | 'daily_minutes' | 'lesson_count' | 'timezone' | 'preload_first_lesson'
>

export function CourseCreateOptions({
  value,
  onChange,
  disabled,
}: {
  value: CourseCreateOptionsValue
  onChange: (patch: Partial<CourseCreateOptionsValue>) => void
  disabled: boolean
}) {
  return (
    <fieldset className="course-form-fields course-create-options" disabled={disabled}>
      <legend className="sr-only">学习安排</legend>
      <label>
        希望学会什么
        <textarea
          rows={2}
          maxLength={1000}
          value={value.goal || ''}
          onChange={(event) => onChange({ goal: event.target.value })}
          placeholder="例如：能编写函数，并解释参数和返回值（选填）"
        />
      </label>
      <label>
        已有基础
        <textarea
          rows={2}
          maxLength={1000}
          value={value.prior_knowledge || ''}
          onChange={(event) => onChange({ prior_knowledge: event.target.value })}
          placeholder="例如：会使用变量和循环（选填）"
        />
      </label>
      <div className="course-form-numbers">
        <label>
          每天学习时长（分钟）
          <input
            type="number"
            min={5}
            max={120}
            step={1}
            required
            value={Number.isNaN(value.daily_minutes) ? '' : value.daily_minutes}
            onChange={(event) => onChange({ daily_minutes: event.target.valueAsNumber })}
          />
        </label>
        <label>
          课程节数
          <input
            type="number"
            min={1}
            max={10}
            step={1}
            required
            value={Number.isNaN(value.lesson_count) ? '' : value.lesson_count}
            onChange={(event) => onChange({ lesson_count: event.target.valueAsNumber })}
          />
        </label>
      </div>
      <label>
        学习时区
        <input
          required
          maxLength={100}
          list="xunke-timezones"
          value={value.timezone}
          onChange={(event) => onChange({ timezone: event.target.value })}
        />
        <datalist id="xunke-timezones">
          {['Asia/Shanghai', 'Asia/Urumqi', 'Asia/Hong_Kong', 'Asia/Taipei', 'Asia/Singapore', 'Asia/Tokyo', 'Asia/Seoul', 'UTC', 'America/Los_Angeles', 'America/New_York', 'Europe/London', 'Europe/Berlin'].map((zone) => <option value={zone} key={zone} />)}
        </datalist>
        <small className="muted">按此时区安排每日复习，可直接选择常用时区。</small>
      </label>
      <label className="check-option">
        <input
          type="checkbox"
          checked={value.preload_first_lesson}
          onChange={(event) => onChange({ preload_first_lesson: event.target.checked })}
        />
        <span>
          创建后立即准备第一课内容
          <small className="muted">
            纲要生成后马上开始第一课，进入课程即可阅读；勾选后标题在开始生成时固定，想先调整标题请取消勾选。
          </small>
        </span>
      </label>
    </fieldset>
  )
}
