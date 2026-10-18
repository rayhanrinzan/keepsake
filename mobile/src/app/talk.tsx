import { Mic, Send, Square } from 'lucide-react-native'
import { useEffect, useRef, useState } from 'react'
import { Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native'
import { ItemRow } from '../components/ItemRow'
import { Glow, Screen, T, st } from '../components/ui'
import { answer } from '../lib/assistant'
import type { TrackedObject } from '../lib/api'
import { useSettings } from '../lib/settings'
import { C, F } from '../lib/theme'
import { canListen, listen, speak, stopSpeaking } from '../lib/voice'

type Turn = { who: 'me' | 'keepsake'; text: string; object?: TrackedObject | null }

const STARTERS = ['Where are my keys?', 'Where are my glasses?', 'What day is it?']

export default function Talk() {
  const { s: prefs } = useSettings()
  const [turns, setTurns] = useState<Turn[]>([{ who: 'keepsake', text: 'Hi, I\'m here. What are you looking for?' }])
  const [heard, setHeard] = useState('')
  const [listening, setListening] = useState(false)
  const [typed, setTyped] = useState('')
  const stop = useRef<(() => void) | null>(null)
  const scroll = useRef<any>(null)
  const voice = canListen()

  useEffect(() => () => { stop.current?.(); stopSpeaking() }, [])

  async function send(text: string) {
    const q = text.trim()
    if (!q) return
    setTurns(t => [...t, { who: 'me', text: q }])
    const reply: Turn = { who: 'keepsake', ...(await answer(q)) }
    setTurns(t => [...t, reply])
    speak(reply.text, prefs, () => { if (prefs.listenAfterSpeaking && voice) toggleMic() })
  }

  function toggleMic() {
    if (listening) return stop.current?.()
    stopSpeaking()
    setHeard('')
    setListening(true)
    stop.current = listen(
      (text, final) => {
        setHeard(text)
        if (final) {
          setHeard('')
          send(text)
        }
      },
      () => setListening(false),
    )
  }

  return (
    <Screen title="Talk to me" scroll={false}>
      <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={{ gap: 12, paddingBottom: 16 }} onContentSizeChange={() => scroll.current?.scrollToEnd()}>
        {turns.map((t, i) => (
          <View key={i} style={[s.bubble, t.who === 'me' ? s.me : s.them]}>
            <T size={20} color={t.who === 'me' ? '#fff' : C.ink}>{t.text}</T>
            {t.object && <View style={{ marginTop: 12 }}><ItemRow o={t.object} /></View>}
          </View>
        ))}
        {heard !== '' && <View style={[s.bubble, s.me, { opacity: 0.6 }]}><T size={20} color="#fff">{heard}</T></View>}
        {turns.length === 1 && (
          <View style={s.starters}>
            {STARTERS.map(q => (
              <Pressable key={q} onPress={() => send(q)} style={({ pressed }) => [s.chip, pressed && st.pressed]}>
                <T size={17} weight="medium">{q}</T>
              </Pressable>
            ))}
          </View>
        )}
      </ScrollView>

      {voice ? (
        <View style={{ alignItems: 'center', gap: 8 }}>
          <Pressable onPress={toggleMic} accessibilityRole="button" accessibilityLabel={listening ? 'Stop listening' : 'Start talking'} style={({ pressed }) => pressed && st.pressed}>
            <Glow style={s.mic} colors={['#fff3b8', C.yellow, C.yellowDeep]}><View style={s.over}>{listening ? <Square size={34} color={C.ink} fill={C.ink} /> : <Mic size={44} color={C.ink} />}</View></Glow>
          </Pressable>
          <T size={17} color={C.muted}>{listening ? 'Listening…' : 'Tap and talk'}</T>
        </View>
      ) : (
        // Phones need a development build for speech to text; typing works everywhere until then.
        <View style={s.type}>
          <TextInput value={typed} onChangeText={setTyped} onSubmitEditing={() => { send(typed); setTyped('') }} placeholder="Ask me anything" placeholderTextColor={C.muted} style={s.input} returnKeyType="send" />
          <Pressable onPress={() => { send(typed); setTyped('') }} accessibilityLabel="Send" style={({ pressed }) => pressed && st.pressed}>
            <View style={[s.send, { backgroundColor: C.black }]}><Send size={24} color="#fff" /></View>
          </Pressable>
        </View>
      )}
    </Screen>
  )
}

const s = StyleSheet.create({
  bubble: { maxWidth: '88%', borderRadius: 24, paddingHorizontal: 18, paddingVertical: 14 },
  me: { alignSelf: 'flex-end', backgroundColor: C.black, borderBottomRightRadius: 6 },
  them: { alignSelf: 'flex-start', backgroundColor: C.glass, borderBottomLeftRadius: 6 },
  starters: { gap: 10, marginTop: 8 },
  chip: { alignSelf: 'flex-start', borderWidth: 1.5, borderColor: C.rim, backgroundColor: 'rgba(255,255,255,0.6)', borderRadius: 999, paddingHorizontal: 18, paddingVertical: 12 },
  mic: { width: 104, height: 104, borderRadius: 52, alignItems: 'center', justifyContent: 'center' },
  type: { flexDirection: 'row', gap: 10, alignItems: 'center' },
  input: { flex: 1, minHeight: 60, borderRadius: 30, borderWidth: 1.5, borderColor: C.rim, backgroundColor: '#fff', paddingHorizontal: 22, fontSize: 19, fontFamily: F.regular, color: C.ink },
  over: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, alignItems: 'center', justifyContent: 'center' },
  send: { width: 60, height: 60, borderRadius: 30, alignItems: 'center', justifyContent: 'center' },
})
