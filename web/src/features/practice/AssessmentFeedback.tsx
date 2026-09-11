import type { PracticeAssessment, PracticeAttempt } from '../../types/practice'

type Assessment = Pick<PracticeAssessment, 'status' | 'score' | 'confirmation' | 'feedback'> &
  Partial<Pick<PracticeAssessment, 'criterion_results' | 'source'>>
export function AssessmentFeedback({
  assessment,
  jobStatus,
}: {
  assessment: Assessment | null
  jobStatus?: PracticeAttempt['grading_status']
}) {
  if (!assessment)
    return (
      <div className="notice" role="status">
        {jobStatus === 'failed'
          ? '评分失败'
          : jobStatus === 'cancelled'
            ? '评分已取消'
            : '评分处理中'}
      </div>
    )
  const label =
    assessment.status === 'failed'
      ? '评分失败'
      : assessment.status === 'cancelled'
        ? '评分已取消'
        : assessment.status === 'needs_review'
          ? '需要复核'
          : assessment.confirmation === 'provisional'
            ? '自动评分，待确认'
            : '评分已确认'
  const graded = assessment.status === 'graded' && assessment.score != null
  return (
    <div className="stack-form practice-feedback" role="status">
      <strong>{label}</strong>
      {graded && (
        <span>
          {assessment.confirmation === 'confirmed' ? '得分' : '参考得分'}{' '}
          {Number((Number(assessment.score) * 100).toFixed(2))}%
        </span>
      )}
      {assessment.feedback && <p>{assessment.feedback}</p>}
      {!!assessment.criterion_results?.length && (
        <ul>
          {assessment.criterion_results.map((item, index) => (
            <li key={item.criterion_id}>
              要点 {index + 1}：
              {
                (
                  {
                    full: '完整',
                    half: '部分满足',
                    none: '尚未满足',
                    uncertain: '需要复核',
                  } as const
                )[item.credit]
              }
              {item.rationale ? ` · ${item.rationale}` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
