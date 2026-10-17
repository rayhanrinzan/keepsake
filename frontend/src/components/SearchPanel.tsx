import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, Mic, Search, Square } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { QueryResult, TrackedObject } from '../lib/api'
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
// A bare "yes" names no item, so we ask which one. "Yes, my keys" goes straight to the lookup.
const AFFIRM = /^(yes|yeah|yep|yup|ya|sure|i am|uh[- ]?huh|please|yes please|kind of|maybe)[.!]?$/i

function joinList(names: string[], last: 'and' | 'or') {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')}, ${last} ${names.at(-1)}`
}

/** "Okay, which item?" plus the items Keepsake has seen (or, if none yet, everything it tracks). */
function whichItem(objects: TrackedObject[]) {
  const seen = objects.filter((o) => o.seen).map((o) => o.name.toLowerCase())
  if (seen.length) return `Okay, which item? I've seen your ${joinList(seen, 'and')}.`
  const all = objects.map((o) => o.name.toLowerCase())
  return all.length ? `Okay, which item? I can look for your ${joinList(all, 'or')}.` : 'Okay, which item?'
}

export function SearchPanel({ onResult, prompt, objects = [] }: {
  onResult: (r: QueryResult) => void
  objects?: TrackedObject[]
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

  /** Say `question`, then listen for one reply. Null if the conversation ended (error/cancel). */
  async function ask(question: string, id: number): Promise<string | null> {
    setPhase('PROMPTING')
    await speak(question) // the mic opens only after the prompt finishes
    if (id !== run.current) return null
    setPhase('LISTENING')
    setHeard('')
    try {
      const said = await listenOnce(setHeard)
      if (id !== run.current) return null
      setHeard(said)
      return said
    } catch (e) {
      if (id !== run.current) return null
      const ve = e instanceof VoiceError ? e : new VoiceError('other', 'Voice input stopped unexpectedly.')
      if (ve.code === 'aborted') return null
      setError(ve.code === 'no-speech' ? "I didn't hear anything. Press Voice to try again." : ve.message)
      setPhase('IDLE')
      if (ve.code === 'no-speech') await speak("I didn't hear anything.")
      return null
    }
  }

  async function declined(id: number) {
    setPhase('RESPONDING')
    await speak('Okay.')
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
    let said = await ask(question, id)
    if (said === null) return
    if (DECLINE.test(said)) return declined(id)
    if (AFFIRM.test(said.trim())) {
      const follow = whichItem(objects)
      setAnswer(follow)
      said = await ask(follow, id)
      if (said === null) return
      if (DECLINE.test(said)) return declined(id)
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
          className="glossy press relative flex h-12 shrink-0 items-center gap-2 rounded-xl pr-5 pl-4 font-medium text-white"
        >
          {listening && <span aria-hidden className="listening-ring absolute inset-0 rounded-xl bg-deep/40" />}
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
            className="h-12 w-full rounded-xl border border-hairline bg-canvas pr-3 pl-10 outline-none placeholder:text-faint focus:border-deep/50 focus:bg-surface"
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
