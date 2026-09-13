import { useEffect, useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { applyContentFrame, subscribeContentEvents } from '../../services/contentEvents'
import { recordExperienceEvent, takeContentSubmittedAt } from '../../services/experienceEvents'
import { getSessionRevision } from '../../services/http'
import { emptyContentPreview, type ContentPreviewState } from '../../types/contentEvent'

export function useContentEvents({ kind, taskId, enabled = true, onFinalized }: {
  kind: 'course' | 'qa'; taskId?: string; enabled?: boolean; onFinalized?: () => void
}): ContentPreviewState {
  const identity = useIdentityKey()
  const session = getSessionRevision()
  const [state, setState] = useState<ContentPreviewState>(emptyContentPreview)
  const contextKey = `${identity}:${session}:${taskId || ''}`
  const visibleContext = useRef(contextKey)
  const finalRef = useRef(onFinalized)
  finalRef.current = onFinalized
  useEffect(() => {
    visibleContext.current = contextKey
    setState({ ...emptyContentPreview, taskId })
    if (!enabled || !taskId) return
    let current = true
    let firstVisible = false
    let controller: AbortController | undefined
    const start = () => {
      if (document.hidden || controller) return
      controller = new AbortController()
      void subscribeContentEvents({
        kind, taskId, signal: controller.signal,
        onFrame: frame => {
          if (!current) return
          setState(previous => applyContentFrame(previous, frame))
          if (!firstVisible && (frame.payload.text || frame.payload.validated_blocks?.length)) {
            firstVisible = true
            const started = takeContentSubmittedAt(taskId)
            // Restored tasks have no client submission clock. Do not report a
            // reconnect latency as the original generation wait.
            if (started !== undefined) {
              void recordExperienceEvent({ event_id: crypto.randomUUID(), name: 'content_first_visible', task_id: taskId,
                elapsed_ms: Math.min(86400000, Math.max(0, Math.round(performance.now() - started))) })
            }
          }
          if (frame.type === 'finalized') finalRef.current?.()
        },
        onInterrupted: () => {
          if (!current) return
          setState(previous => ({ ...previous, status: 'reconnecting' }))
          void recordExperienceEvent({ event_id: crypto.randomUUID(), name: 'content_stream_interrupted', task_id: taskId })
        },
        onUnavailable: () => {
          if (current) setState(previous => ({ ...previous, text: '', blocks: [], status: 'unavailable' }))
        },
      })
    }
    const visibility = () => {
      if (document.hidden) { controller?.abort(); controller = undefined }
      else start()
    }
    document.addEventListener('visibilitychange', visibility)
    start()
    return () => { current = false; controller?.abort(); document.removeEventListener('visibilitychange', visibility) }
  }, [enabled, kind, taskId, identity, session, contextKey])
  // Do not expose old-user/task content for the render before effects run.
  return state.taskId === taskId && visibleContext.current === contextKey ? state : { ...emptyContentPreview, taskId }
}
