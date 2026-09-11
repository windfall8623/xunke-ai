import { ArrowLeft, ArrowRight, CheckCircle2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

/** Static onboarding examples are isolated from production learning records and AI calls. */
const preset = [
  {
    stem: '学习一段新知识后，哪种做法更能帮助你检验理解？',
    options: ['立刻反复抄写全部笔记', '尝试不看笔记回忆要点', '只看自己已经熟悉的内容'],
    answer: 1,
    explanation:
      '主动回忆会暴露理解中的空白。回忆后再核对内容，通常比单纯重复阅读更有助于发现薄弱点。',
  },
  {
    stem: '一道练习题答错了，下一步更有价值的做法是什么？',
    options: ['回到依据，找出自己的推理在哪一步偏离', '只记住正确选项的字母', '跳过所有类似的问题'],
    answer: 0,
    explanation:
      '错题的价值在于帮助你定位推理或概念上的问题。理解原理之后，再用不同例子验证掌握情况。',
  },
  {
    stem: '练习结束后，如何安排下一次学习更合适？',
    options: ['只重复已经全对的题', '不再复习', '间隔一段时间，再练习薄弱知识点'],
    answer: 2,
    explanation: '把复习分散在不同时间，并优先关注薄弱点，可以避免把短时间的熟悉误认为长久掌握。',
  },
]
export function DemoPage() {
  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [finished, setFinished] = useState(false)
  const question = preset[index]
  const saved = answers[index] !== undefined
  return (
    <div className="narrow-page">
      <Link className="back-link" to="/">
        <ArrowLeft size={16} />
        返回首页
      </Link>
      <div className="notice demo-notice">
        <Sparkles size={19} />
        <div>
          <strong>预置体验 · 不调用 AI</strong>
          <p>这是固定示例，不计入学习历史与经验值。正式练习会保存服务端进度。</p>
        </div>
      </div>
      <header className="page-heading">
        <div>
          <p className="eyebrow">A SMALL STEP TO GET STARTED</p>
          <h1>高效学习，从理解开始</h1>
          <p className="muted">用 3 道小题，体验一次学习的过程。</p>
        </div>
      </header>
      {finished ? (
        <section className="card demo-finish">
          <CheckCircle2 size={38} />
          <h2>体验完成，真正的探索现在开始。</h2>
          <p>登录后，你可以选择自己的主题与资料，保存每一次进步。</p>
          <Link to="/login" className="button primary">
            开始我的学习
            <ArrowRight size={18} />
          </Link>
        </section>
      ) : (
        <section className="card question-card">
          <div className="question-meta">
            <span className="badge question-type">单选题</span>
            <span className="question-number">{index + 1} / 3</span>
          </div>
          <h2>{question.stem}</h2>
          <fieldset className="answer-options" disabled={saved}>
            <legend className="sr-only">选择答案</legend>
            {question.options.map((option, value) => (
              <label
                className={`answer-option ${selected === value ? 'selected' : ''} ${saved && value === question.answer ? 'correct' : ''}`}
                key={option}
              >
                <input
                  name="preset-answer"
                  type="radio"
                  checked={selected === value}
                  onChange={() => setSelected(value)}
                />
                <span className="option-key">{String.fromCharCode(65 + value)}</span>
                <span>{option}</span>
              </label>
            ))}
          </fieldset>
          {saved && (
            <div className="answer-feedback" role="status">
              <strong>
                {answers[index] === question.answer ? '回答正确' : '看看这道题的思路'}
              </strong>
              <p>{question.explanation}</p>
            </div>
          )}
          <div className="question-actions">
            <span className="tiny muted">仅供体验 · 本页刷新会重置</span>
            {saved ? (
              <button
                className="button primary"
                onClick={() => {
                  if (index === preset.length - 1) setFinished(true)
                  else {
                    setIndex(index + 1)
                    setSelected(null)
                  }
                }}
              >
                {index === preset.length - 1 ? '完成体验' : '下一题'}
                <ArrowRight size={16} />
              </button>
            ) : (
              <button
                className="button primary"
                disabled={selected === null}
                onClick={() => {
                  if (selected !== null)
                    setAnswers((current) => ({ ...current, [index]: selected }))
                }}
              >
                提交答案
              </button>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
