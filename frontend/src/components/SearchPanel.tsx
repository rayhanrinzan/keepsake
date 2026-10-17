import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, Mic, Search, Square } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { QueryResult } from '../lib/api'
import { listenOnce, speak, speechInputSupported, stopVoice, VoiceError } from '../lib/voice'

/** Conversation: IDLE → PROMPTING → LISTENING → LOOKING_UP → RESPONDING → IDLE */
type Phase = 'IDLE' | 'PROMPTING' | 'LISTENING' | 'LOOKING_UP' | 'RESPONDING'

const PHASE_LABEL: Record<Phase, string> = {
  IDLE: '',
  PROMPTING: 'Asking what you’re looking for…',
  LISTENING: 'Listening. Say the item, like “my water bottle”.',
  LOOKING_UP: 'Checking memory…',
  RESPONDING: 'Answering…',
}

const DECLINE = /^(no|nope|nah|nothing|i'?m (good|fine|ok(ay)?)|not really|no thanks?)\b/i

export function SearchPanel({ onResult, prompt }: {
  onResult: (r: QueryResult) => void
  /** Ask unprompted (e.g. someone walked out of view). A new id starts a new conversation. */
  prompt?: { id: number; text: string } | null
}) {
  const [phase, setPhase] = useState<Phase>('IDLE')
  const [heard, setHeard] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const run = useRef(0) // increments to cancel an in-flight conversation

  const phaseRef = useRef<Phase>('IDLE')
  phaseRef.current = phase

  useEffect(() => () => stopVoice(), [])

  useEffect(() => {
    // Don't interrupt a conversation that's already going.
    if (prompt && phaseRef.current === 'IDLE') startVoice(prompt.text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt?.id])

  async function lookUp(q: string, id: number, spoken: boolean) {
    setPhase('LOOKING_UP')
    let r: QueryResult
    try {
      r = await api.query(q)
    } catch (e) {
      if (id !== run.current) return
      const msg = e instanceof ApiError && e.status === 0
        ? "I can't reach Keepsake's memory right now. Check that the backend is running."
        : 'Something went wrong looking that up.'
      setError(msg)
      setPhase('IDLE')
      if (spoken) await speak(msg)
      return
    }
    if (id !== run.current) return
    setAnswer(r.answer)
    onResult(r)
    setPhase('RESPONDING')
    await speak(r.answer)
    if (id === run.current) setPhase('IDLE')
  }

  async function startVoice(question = 'What are you looking for?') {
    const id = ++run.current
    setError(null)
    setAnswer(null)
    setHeard('')
    if (!speechInputSupported) {
      setError("Voice isn't available in this browser. Type instead, or use Chrome, Edge or Safari.")
      return
    }
    setPhase('PROMPTING')
    await speak(question) // the mic opens only after the prompt finishes
    if (id !== run.current) return
    setPhase('LISTENING')
    let said: string
    try {
      said = await listenOnce(setHeard)
    } catch (e) {
      if (id !== run.current) return
      const ve = e instanceof VoiceError ? e : new VoiceError('other', 'Voice input stopped unexpectedly.')
      if (ve.code === 'aborted') return
      setError(ve.code === 'no-speech' ? "I didn't hear anything. Press Voice to try again." : ve.message)
      setPhase('IDLE')
      if (ve.code === 'no-speech') await speak("I didn't hear anything.")
      return
    }
    if (id !== run.current) return
    setHeard(said)
    if (DECLINE.test(said)) {
      setPhase('RESPONDING')
      await speak('Okay.')
      if (id === run.current) setPhase('IDLE')
      return
    }
    await lookUp(said, id, true)
  }

  function stop() {
    run.current++
    stopVoice()
    setPhase('IDLE')
  }

  async function submitTyped(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    const id = ++run.current
    stopVoice()
    setError(null)
    setHeard('')
    await lookUp(text, id, false)
  }

  const busy = phase !== 'IDLE'
  const listening = phase === 'LISTENING'

  return (
    <section className="card rounded-[24px] p-3">{/* outer 24 = input 12 + padding 12 */}
      <div className="flex gap-2">
        <button
          onClick={busy ? stop : () => startVoice()}
          aria-label={busy ? 'Stop voice assistant' : 'Ask by voice'}
          className="press relative flex h-12 shrink-0 items-center gap-2 rounded-xl bg-ink pr-5 pl-4 font-medium text-white hover:bg-ink/85"
        >
          {listening && <span aria-hidden className="listening-ring absolute inset-0 rounded-xl bg-ink/40" />}
          {busy ? <Square className="relative size-4 fill-current" strokeWidth={1.75} /> : <Mic className="relative size-[18px]" strokeWidth={1.75} />}
          <span className="relative">{listening ? 'Listening' : busy ? 'Stop' : 'Voice'}</span>
        </button>

        <form onSubmit={submitTyped} className="relative min-w-0 flex-1">
          <label htmlFor="ask" className="sr-only">Ask where something is</label>
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-faint" strokeWidth={1.75} />
          <input
            id="ask"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Where is my phone?"
            className="h-12 w-full rounded-xl border border-hairline bg-canvas pr-3 pl-10 outline-none placeholder:text-faint focus:border-ink/40 focus:bg-surface"
          />
        </form>
      </div>

      {(busy || answer || error || heard) && (
        <div className="space-y-1 px-1 pt-3 pb-1" aria-live="polite">
          {busy && (
            <p className="flex items-center gap-2 text-[14px] text-muted">
              {phase === 'LOOKING_UP' && <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" strokeWidth={1.75} />}
              {PHASE_LABEL[phase]}
            </p>
          )}
          {heard && <p className="text-[14px] text-muted">You said “{heard}”</p>}
          {answer && phase !== 'LOOKING_UP' && <p className="text-[17px] leading-snug font-medium">{answer}</p>}
          {error && <p className="text-[14px] text-caution">{error}</p>}
        </div>
      )}
    </section>
  )
}
