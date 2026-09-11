import { X } from 'lucide-react'
import { useId, useLayoutEffect, useRef, type ReactNode } from 'react'

export function Dialog({
  title,
  onClose,
  children,
  className = '',
}: {
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useLayoutEffect(() => {
    const dialog = ref.current!
    const returnFocusTo =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    }
    return () => {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      if (returnFocusTo?.isConnected) returnFocusTo.focus({ preventScroll: true })
    }
  }, [])
  return (
    <dialog
      ref={ref}
      className={`dialog ${className}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const rect = event.currentTarget.getBoundingClientRect()
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          onClose()
      }}
    >
      <header className="dialog-header">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="icon-button" aria-label={`关闭${title}`} onClick={onClose}>
          <X size={19} />
        </button>
      </header>
      <div className="dialog-body">{children}</div>
    </dialog>
  )
}
