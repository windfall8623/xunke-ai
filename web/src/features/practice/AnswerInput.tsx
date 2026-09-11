import type { PracticeAnswer, PracticeQuestion } from '../../types/practice'

export function emptyPracticeAnswer(question: PracticeQuestion): PracticeAnswer {
  switch (question.type) {
    case 'cloze':
      return {
        type: 'cloze',
        blanks: question.blank_ids.map((blank_id) => ({ blank_id, text: '' })),
      }
    case 'numeric':
      return { type: 'numeric', value: '', unit: question.unit }
    case 'short_answer':
      return { type: 'short_answer', text: '' }
  }
}

export function AnswerInput({
  question,
  value,
  onChange,
  disabled = false,
}: {
  question: PracticeQuestion
  value: PracticeAnswer
  onChange: (answer: PracticeAnswer) => void
  disabled?: boolean
}) {
  switch (question.type) {
    case 'cloze': {
      const blanks = value.type === 'cloze' ? value.blanks : []
      return (
        <fieldset className="stack-form" disabled={disabled}>
          <legend>填写各空</legend>
          {question.blank_ids.map((id, index) => (
            <label key={id}>
              第 {index + 1} 空
              <input
                maxLength={500}
                value={blanks.find((blank) => blank.blank_id === id)?.text || ''}
                onChange={(event) =>
                  onChange({
                    type: 'cloze',
                    blanks: question.blank_ids.map((blank_id) => ({
                      blank_id,
                      text:
                        blank_id === id
                          ? event.target.value
                          : blanks.find((blank) => blank.blank_id === blank_id)?.text || '',
                    })),
                  })
                }
              />
            </label>
          ))}
        </fieldset>
      )
    }
    case 'numeric':
      return (
        <label>
          数值答案{question.unit ? `（${question.unit}）` : ''}
          <input
            type="text"
            inputMode="decimal"
            required
            disabled={disabled}
            value={value.type === 'numeric' ? value.value : ''}
            onChange={(event) =>
              onChange({ type: 'numeric', value: event.target.value, unit: question.unit })
            }
          />
          <small>按题目单位填写，支持小数和科学计数法。</small>
        </label>
      )
    case 'short_answer':
      return (
        <label>
          你的解释
          <textarea
            rows={5}
            required
            maxLength={2000}
            disabled={disabled}
            value={value.type === 'short_answer' ? value.text : ''}
            onChange={(event) => onChange({ type: 'short_answer', text: event.target.value })}
          />
          <small>{value.type === 'short_answer' ? value.text.length : 0}/2000 字</small>
        </label>
      )
  }
}
