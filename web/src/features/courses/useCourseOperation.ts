import { useCallback, useEffect, useRef, useState } from 'react'
import { isUnconfirmedCourseOperation, type CourseOperationState } from './courseActionState'

/** One explicit operation at a time; leaving the account/page discards its callbacks. */
export function useCourseOperation() {
  const controller = useRef<AbortController | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [state, setState] = useState<CourseOperationState>({ kind: 'idle' })
  useEffect(() => () => controller.current?.abort(), [])
  const run = useCallback(
    async <T>(
      name: string,
      request: (signal: AbortSignal) => Promise<T>,
      onSuccess?: (value: T) => void,
    ) => {
      if (controller.current) return undefined
      const current = new AbortController()
      controller.current = current
      setPending(name)
      setError(null)
      setState({ kind: 'submitting', operation: name })
      try {
        const value = await request(current.signal)
        if (!current.signal.aborted) {
          onSuccess?.(value)
          setState({ kind: 'confirmed', operation: name })
          return value
        }
      } catch (cause) {
        if (!current.signal.aborted) {
          setError(cause)
          setState({
            kind: isUnconfirmedCourseOperation(cause) ? 'unconfirmed' : 'failed',
            operation: name,
          })
        }
      } finally {
        if (controller.current === current) controller.current = null
        if (!current.signal.aborted) setPending(null)
      }
      return undefined
    },
    [],
  )
  const confirm = useCallback((name: string) => {
    setError(null)
    setState({ kind: 'confirmed', operation: name })
  }, [])
  return { pending, error, setError, state, confirm, run }
}
