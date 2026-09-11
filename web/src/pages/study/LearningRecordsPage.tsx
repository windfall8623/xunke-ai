import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { EmptyState, ErrorNotice, Loading, PageHeading } from '../../components/ui'
import { AttemptTimeline, projectionLabels, studyDate } from '../../features/study/AttemptTimeline'
import { studyApi, studyErrorMessage, studyKeys } from '../../services/study'
import type { StudyWrongQuestion } from '../../types/study'
import { StudyNavigation } from './ReviewPage'

export function LearningRecordsPage({ kind }: { kind: 'history' | 'wrong' }) {
  const identity = useIdentityKey()
  const [params] = useSearchParams()
  const spaceId = params.get('space_id') || ''
  const conceptId = params.get('concept_id') || ''
  return (
    <Records
      key={`${identity}:${kind}:${spaceId}:${conceptId}`}
      kind={kind}
      initialSpace={spaceId}
      initialConcept={conceptId}
    />
  )
}

function Records({
  kind,
  initialSpace,
  initialConcept,
}: {
  kind: 'history' | 'wrong'
  initialSpace: string
  initialConcept: string
}) {
  const identity = useIdentityKey()
  const [spaceId, setSpaceId] = useState(initialSpace)
  const [conceptId, setConceptId] = useState(initialConcept)
  const [cursor, setCursor] = useState<string>()
  const [questionType, setQuestionType] = useState<StudyWrongQuestion['question_type'] | ''>('')
  const spaces = useQuery({
    queryKey: studyKeys.spaces(identity),
    queryFn: ({ signal }) => studyApi.spaces(1, undefined, signal),
    retry: false,
  })
  const concepts = useQuery({
    queryKey: studyKeys.concepts(identity, spaceId),
    queryFn: ({ signal }) => studyApi.concepts(spaceId, signal),
    enabled: !!spaceId,
    retry: false,
  })
  const filters = {
    space_id: spaceId || undefined,
    concept_id: conceptId || undefined,
    cursor,
    ...(kind === 'wrong' && questionType ? { question_type: questionType } : {}),
  }
  const history = useQuery({
    queryKey: studyKeys.history(identity, filters),
    queryFn: ({ signal }) => studyApi.history(filters, signal),
    enabled: kind === 'history',
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const wrong = useQuery({
    queryKey: studyKeys.wrongQuestions(identity, filters),
    queryFn: ({ signal }) => studyApi.wrongQuestions(filters, signal),
    enabled: kind === 'wrong',
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const query = kind === 'history' ? history : wrong
  return (
    <div className="stack-form">
      <PageHeading
        eyebrow="知学 AI · 学习记录"
        title={kind === 'history' ? '学习历史' : '跨套错题本'}
        description={
          kind === 'history'
            ? '保留每次学习活动和评分确认的实际记录。'
            : '按概念回看错误与部分正确的作答；后续答对也会保留此前记录。'
        }
      />
      <StudyNavigation />
      <div className="button-row">
        <label>
          学习空间
          <select
            value={spaceId}
            onChange={(event) => {
              setSpaceId(event.target.value)
              setConceptId('')
              setCursor(undefined)
            }}
          >
            <option value="">全部空间</option>
            {spaces.data?.items
              .filter((item) => item.source_status === 'active')
              .map((space) => (
                <option key={space.space_id} value={space.space_id}>
                  {space.title}
                </option>
              ))}
          </select>
        </label>
        <label>
          学习概念
          <select
            value={conceptId}
            disabled={!spaceId}
            onChange={(event) => {
              setConceptId(event.target.value)
              setCursor(undefined)
            }}
          >
            <option value="">全部概念</option>
            {concepts.data?.items
              .filter((item) => item.source_status === 'active')
              .map((concept) => (
                <option key={concept.concept_id} value={concept.concept_id}>
                  {concept.title}
                </option>
              ))}
          </select>
        </label>
        {kind === 'wrong' && (
          <label>
            题型
            <select
              value={questionType}
              onChange={(event) => {
                setQuestionType(event.target.value as typeof questionType)
                setCursor(undefined)
              }}
            >
              <option value="">全部题型</option>
              <option value="single">单选</option>
              <option value="multiple">多选</option>
              <option value="judge">判断</option>
              <option value="cloze">填空</option>
              <option value="numeric">数值</option>
              <option value="short_answer">短解释</option>
            </select>
          </label>
        )}
      </div>
      {query.error ? (
        <ErrorNotice
          error={studyErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : !query.data ? (
        <Loading>正在读取学习记录…</Loading>
      ) : kind === 'history' ? (
        <AttemptTimeline items={history.data?.items || []} />
      ) : !wrong.data?.items.length ? (
        <EmptyState title="当前筛选下还没有错题">
          只有已确认评分的错误和部分正确作答会进入错题本。
        </EmptyState>
      ) : (
        <ul className="study-record-list">
          {wrong.data.items.map((item) => (
            <WrongQuestion key={item.item_id} item={item} />
          ))}
        </ul>
      )}
      {query.data && (
        <div className="button-row">
          <button
            className="button secondary"
            disabled={!cursor}
            onClick={() => setCursor(undefined)}
          >
            返回第一页
          </button>
          {query.data.next_cursor && (
            <button
              className="button secondary"
              onClick={() => setCursor(query.data!.next_cursor!)}
            >
              下一页
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function renderAnswer(value: unknown): string {
  if (value == null) return '未保存答案'
  if (Array.isArray(value)) return value.map(renderAnswer).join('、')
  if (typeof value === 'object')
    return Object.entries(value)
      .filter(([key]) => key !== 'type')
      .map(
        ([key, item]) =>
          `${['value', 'text', 'selected_answers'].includes(key) ? '' : `${key}：`}${renderAnswer(item)}`,
      )
      .join('；')
  return String(value)
}

function WrongQuestion({ item }: { item: StudyWrongQuestion }) {
  if (item.source_status !== 'active')
    return <li className="card notice">资料已失效，相关题目和作答已隐藏。</li>
  return (
    <li className="card stack-form">
      <div className="button-row">
        <span className="badge">{item.result_status === 'partial' ? '部分正确' : '回答错误'}</span>
        <time dateTime={item.occurred_at}>{studyDate(item.occurred_at)}</time>
        {item.association_status === 'unlinked' && (
          <span className="tiny muted">历史题目 · 未关联概念</span>
        )}
      </div>
      <h2>{item.question?.stem || '题目暂时不可用'}</h2>
      <p>我的答案：{renderAnswer(item.answer)}</p>
      {item.correct_answers.length > 0 && <p>参考答案：{item.correct_answers.join('、')}</p>}
      {(item.current_assessment?.feedback || item.feedback) && (
        <p>{item.current_assessment?.feedback || item.feedback}</p>
      )}
      <p className="tiny muted">{projectionLabels[item.projection_status]}</p>
      <div className="button-row">
        {item.concepts.map((concept) => (
          <Link
            className="text-button"
            key={concept.concept_id}
            to={`/study/concepts/${encodeURIComponent(concept.concept_id)}`}
          >
            {concept.title}
          </Link>
        ))}
        <Link
          className="button secondary"
          to={
            item.origin_kind === 'quiz'
              ? `/quizzes/${encodeURIComponent(item.origin_id)}`
              : `/practice/${encodeURIComponent(item.origin_id)}`
          }
        >
          查看原练习
        </Link>
        {item.concepts[0] && (
          <Link
            className="button secondary"
            to={`/study/reviews?concept_id=${encodeURIComponent(item.concepts[0].concept_id)}`}
          >
            查看复习安排
          </Link>
        )}
      </div>
    </li>
  )
}
