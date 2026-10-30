// DeepSeek Harness (dsh) plugin: reports agent activity to the deskpet daemon.
//
// DeepSeek Harness has no Claude-style hook files; its extension point is
// Cordis plugins. This one listens to the durable session feed
// ('session/event', docs/user/develop/framework/events.md) and posts the same
// Claude-style hook payloads the other agents send, to
// http://127.0.0.1:$DESKPET_PORT/hook/dsh (port 7878 by default).
//
// Posting is fire-and-forget and strictly ordered; failures are ignored so the
// desk pet can never slow down or break an agent run.

export const name = 'deskpet'

const PORT = process.env.DESKPET_PORT || '7878'
const URL = `http://127.0.0.1:${PORT}/hook/dsh`

let queue = Promise.resolve()

function post(payload) {
  queue = queue
    .then(() => fetch(URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(1000),
    }))
    .catch(() => {})
}

function parseArguments(text) {
  try {
    const value = JSON.parse(text || '{}')
    return value && typeof value === 'object' ? value : {}
  }
  catch {
    return {}
  }
}

// TurnEndReason kinds (packages/core/session/src/types.ts) -> deskpet events.
const TURN_END = {
  completed: 'Stop',
  blocked: 'Stop',
  'max-tokens': 'Stop',
  error: 'StopFailure',
  aborted: 'Interrupt',
  interrupted: 'Interrupt',
}

export function toHook(session, event) {
  const base = { session_id: String(session.id), cwd: session.header?.cwd }
  const data = event.data || {}
  switch (event.type) {
    case 'turn/start':
      return { ...base, hook_event_name: 'UserPromptSubmit' }
    case 'tool/call':
      return { ...base, hook_event_name: 'PreToolUse', tool_name: data.name, tool_input: parseArguments(data.arguments) }
    case 'tool/result':
      return { ...base, hook_event_name: 'PostToolUse' }
    case 'approval/asked':
      return { ...base, hook_event_name: 'PermissionRequest', tool_name: data.toolName }
    case 'approval/decided':
      return { ...base, hook_event_name: 'PermissionGranted' }
    case 'compaction/start':
      return { ...base, hook_event_name: 'PreCompact' }
    case 'compaction/end':
      return { ...base, hook_event_name: 'PostCompact' }
    case 'turn/end': {
      const kind = data.reason?.kind
      const hook = TURN_END[kind]
      if (!hook) return null  // 'forked' and future kinds: leave the state alone
      const out = { ...base, hook_event_name: hook }
      if (hook === 'StopFailure') out.error = String(data.reason?.error?.message || 'failed').slice(0, 200)
      return out
    }
    default:
      return null
  }
}

export function apply(ctx) {
  ctx.on('session/event', (session, event) => {
    const hook = toHook(session, event)
    if (hook) post(hook)
  })
  ctx.on('session/disposed', (session) => {
    post({ session_id: String(session.id), hook_event_name: 'SessionEnd' })
  })
}
