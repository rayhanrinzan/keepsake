import { Platform } from 'react-native'

/**
 * How loud the microphone is, from 0 to 1, about 30 times a second. Browser only for now; a phone
 * needs a development build for live audio, so there it returns nothing.
 */
export function canMeasure() {
  return Platform.OS === 'web' && typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)
}

export function measure(onLevel: (level: number) => void) {
  let stopped = false
  let stopAll = () => {}
  navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
    if (stopped) return stream.getTracks().forEach(t => t.stop())
    const ctx = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    ctx.createMediaStreamSource(stream).connect(analyser)
    const data = new Uint8Array(analyser.fftSize)
    let frame = 0
    const tick = () => {
      analyser.getByteTimeDomainData(data)
      let sum = 0
      for (const v of data) sum += ((v - 128) / 128) ** 2
      onLevel(Math.min(1, Math.sqrt(sum / data.length) * 4))
      frame = requestAnimationFrame(tick)
    }
    tick()
    stopAll = () => {
      cancelAnimationFrame(frame)
      stream.getTracks().forEach(t => t.stop())
      ctx.close()
    }
  }).catch(() => onLevel(0))
  return () => { stopped = true; stopAll() }
}
