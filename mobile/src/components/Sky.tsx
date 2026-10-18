import { StyleSheet, View } from 'react-native'

/** The backdrop: plain white. */
export function Sky() {
  return <View style={[StyleSheet.absoluteFill, { backgroundColor: '#ffffff' }]} />
}
