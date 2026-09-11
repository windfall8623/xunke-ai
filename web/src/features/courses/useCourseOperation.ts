import { useCallback, useEffect, useRef, useState } from 'react'

/** One explicit operation at a time; leaving the account/page discards its callbacks. */
export function useCourseOperation() {
  const controller = useRef<AbortController | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
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
      try {
        const value = await request(current.signal)
        if (!current.signal.aborted) {
          onSuccess?.(value)
          return value
        }
      } catch (cause) {
        if (!current.signal.aborted) setError(cause)
      } finally {
        if (controller.current === current) controller.current = null
        if (!current.signal.aborted) setPending(null)
      }
      return undefined
    },
    [],
  )
  return { pending, error, setError, run }
}
