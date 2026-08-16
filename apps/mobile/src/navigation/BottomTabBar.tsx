/**
 * Adapter between React Navigation's bottom-tabs and the shared `BottomNav`
 * component. Maps each route onto a glyph so the floating glass bar carries
 * its own minimal iconography without an icon dependency.
 */

import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import React from 'react';

import { BottomNav, type BottomNavItem } from '../components/BottomNav';
import type { GlyphName } from '../components/Glyph';

const TAB_GLYPHS: Record<string, GlyphName> = {
  Home: 'chat',
  Live: 'live',
  Camera: 'camera',
  Vision: 'vision',
};

export function BottomTabBar(props: BottomTabBarProps) {
  const { state, descriptors, navigation } = props;
  const items: BottomNavItem[] = state.routes.map((route) => {
    const options = descriptors[route.key]?.options;
    return {
      key: route.key,
      label:
        (options?.tabBarLabel as string | undefined) ??
        (options?.title as string | undefined) ??
        route.name,
      glyph: TAB_GLYPHS[route.name] ?? 'live',
    };
  });

  const activeRoute = state.routes[state.index];
  const activeKey = activeRoute?.key ?? '';

  return (
    <BottomNav
      items={items}
      activeKey={activeKey}
      onSelect={(key) => {
        const route = state.routes.find((r) => r.key === key);
        if (route) {
          navigation.navigate(route.name);
        }
      }}
    />
  );
}