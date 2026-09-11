const prefix = 'qa-submission:'

export function qaSubmissionKey(identity: string | number, sessionId: string) {
  return `${prefix}${identity}:${sessionId}`
}

export function clearQaSubmissions(keepIdentity?: number) {
  try {
    const keepPrefix = keepIdentity === undefined ? null : `${prefix}${keepIdentity}:`
    for (let index = sessionStorage.length - 1; index >= 0; index--) {
      const key = sessionStorage.key(index)
      if (key?.startsWith(prefix) && (!keepPrefix || !key.startsWith(keepPrefix)))
        sessionStorage.removeItem(key)
    }
  } catch {
    /* Browsers may disable storage; no private drafts were persisted there. */
  }
}
