import { MPLUS1_200ExtraLight, MPLUS1_300Light, MPLUS1_400Regular, MPLUS1_500Medium, useFonts } from '@expo-google-fonts/m-plus-1'
import { Quicksand_500Medium } from '@expo-google-fonts/quicksand'
import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { SettingsProvider } from '../lib/settings'

export default function Root() {
  const [loaded] = useFonts({ MPLUS1_200ExtraLight, MPLUS1_300Light, MPLUS1_400Regular, MPLUS1_500Medium, Quicksand_500Medium })
  if (!loaded) return null
  return (
    <SafeAreaProvider>
      <SettingsProvider>
        <StatusBar style="light" />
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: '#1656ad' }, animation: 'fade' }} />
      </SettingsProvider>
    </SafeAreaProvider>
  )
}
