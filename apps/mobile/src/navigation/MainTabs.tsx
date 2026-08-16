import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import React from 'react';

import { CameraScreen } from '../screens/CameraScreen';
import { HomeScreen } from '../screens/HomeScreen';
import { LiveScreen } from '../screens/LiveScreen';
import { VisionScreen } from '../screens/VisionScreen';
import { BottomTabBar } from './BottomTabBar';
import type { MainTabParamList } from './types';

const Tab = createBottomTabNavigator<MainTabParamList>();

const renderTabBar = (props: BottomTabBarProps) => <BottomTabBar {...props} />;

export function MainTabs() {
  return (
    <Tab.Navigator
      tabBar={renderTabBar}
      screenOptions={{
        headerShown: false,
        lazy: true,
        tabBarStyle: {
          backgroundColor: 'transparent',
          borderTopWidth: 0,
          elevation: 0,
        },
      }}>
      <Tab.Screen name="Home" component={HomeScreen} options={{ title: 'Home' }} />
      <Tab.Screen name="Live" component={LiveScreen} options={{ title: 'Live' }} />
      <Tab.Screen name="Camera" component={CameraScreen} options={{ title: 'Camera' }} />
      <Tab.Screen name="Vision" component={VisionScreen} options={{ title: 'Vision' }} />
    </Tab.Navigator>
  );
}