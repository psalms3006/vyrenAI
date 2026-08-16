import {
  DarkTheme,
  NavigationContainer,
  type Theme as NavTheme,
} from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import React from 'react';

import { ModelSheet } from '../screens/ModelSheet';
import { SettingsScreen } from '../screens/SettingsScreen';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';
import { MainTabs } from './MainTabs';
import type { RootStackParamList } from './types';

const Stack = createStackNavigator<RootStackParamList>();

const navigationTheme: NavTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: colors.accent,
    background: colors.background,
    card: colors.surface,
    text: colors.textPrimary,
    border: colors.border,
    notification: colors.accent,
  },
};

export function RootNavigator() {
  return (
    <NavigationContainer theme={navigationTheme}>
      <Stack.Navigator
        initialRouteName="Main"
        screenOptions={{
          headerStyle: { backgroundColor: colors.surface, elevation: 0, shadowOpacity: 0 },
          headerTintColor: colors.textPrimary,
          headerTitleStyle: typography.heading,
          cardStyle: { backgroundColor: colors.background },
        }}>
        <Stack.Screen
          name="Main"
          component={MainTabs}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="Settings"
          component={SettingsScreen}
          options={{ presentation: 'modal', title: 'Settings' }}
        />
        <Stack.Screen
          name="ModelSheet"
          component={ModelSheet}
          options={{ presentation: 'modal', title: 'Model' }}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}