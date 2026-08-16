/* eslint-env jest */
// Global Jest setup for VyrenMobile.
// Native/WebView modules used by the app are mocked here so tests can run
// in Node without a device. Mocks are minimal and module-level — each test
// can override behaviour per-case.

require('react-native-gesture-handler/jestSetup');

// Reanimated renders as static trees in tests. v4's shipped mock pulls in
// the real native worklets module, so we stub the exact surface the app
// uses instead (static values, no animation loop).
jest.mock('react-native-reanimated', () => {
  const { Easing, View, Text, Image, ScrollView, FlatList } =
    require('react-native');
  const noop = () => {};
  const id = (value) => value;
  const useSharedValue = (init) => ({ value: init });
  const useAnimatedStyle = (builder) => (builder ? builder() : {});

  return {
    __esModule: true,
    default: {
      View,
      Text,
      Image,
      ScrollView,
      FlatList,
      createAnimatedComponent: id,
    },
    Easing,
    useSharedValue,
    useAnimatedStyle,
    useDerivedValue: (builder) => ({ value: builder() }),
    useAnimatedReaction: noop,
    useAnimatedRef: () => ({ current: null }),
    withTiming: id,
    withRepeat: id,
    withSequence: () => 0,
    withSpring: id,
    withDelay: (_, next) => next,
    cancelAnimation: noop,
    runOnJS: id,
    runOnUI: id,
  };
});

// Safe-area context ships an official jest mock; it exports under `default`.
jest.mock('react-native-safe-area-context', () =>
  require('react-native-safe-area-context/jest/mock').default,
);

// BlurView renders nothing meaningful headless; swap for a plain View.
jest.mock('@react-native-community/blur', () => {
  const { View } = require('react-native');
  const React = require('react');
  return {
    __esModule: true,
    BlurView: (props) => React.createElement(View, props),
  };
});

// AsyncStorage: in-memory mock (v3 ships no jest mock).
jest.mock('@react-native-async-storage/async-storage', () => {
  const store = new Map();
  const backing = {
    getItem: jest.fn(async (key) => (store.has(key) ? store.get(key) : null)),
    setItem: jest.fn(async (key, value) => {
      store.set(key, String(value));
    }),
    removeItem: jest.fn(async (key) => {
      store.delete(key);
    }),
    clear: jest.fn(async () => {
      store.clear();
    }),
    getAllKeys: jest.fn(async () => Array.from(store.keys())),
    multiGet: jest.fn(async (keys) =>
      keys.map((key) => [key, store.has(key) ? store.get(key) : null]),
    ),
    multiSet: jest.fn(async (pairs) => {
      pairs.forEach(([key, value]) => store.set(key, String(value)));
    }),
    multiRemove: jest.fn(async (keys) => {
      keys.forEach((key) => store.delete(key));
    }),
  };
  return { __esModule: true, default: backing, ...backing };
});