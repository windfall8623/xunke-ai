import { ContentPreview } from '../tasks/ContentPreview'
import { useContentEvents } from '../tasks/useContentEvents'

export function LessonGenerationPreview({ taskId, onFinalized }: { taskId?: string; onFinalized?: () => void }) {
  const state = useContentEvents({ kind: 'course', taskId, onFinalized })
  return <ContentPreview state={state} lesson />
}
