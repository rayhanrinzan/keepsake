import { router } from 'expo-router'
import { Unfold } from '../components/Unfold'

/** The unfolding blueprint on its own, for showing the opening again. Home plays it on launch. */
export default function Intro() {
  return <Unfold onDone={() => router.replace('/')} />
}
