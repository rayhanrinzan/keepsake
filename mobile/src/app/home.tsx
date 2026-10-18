import { Redirect } from 'expo-router'

// The old blocky home. The app's home is now the orange page at /, so this just sends people there.
export default function OldHome() {
  return <Redirect href="/" />
}
