module.exports = {
  preset: '@react-native/jest-preset',
  setupFiles: ['<rootDir>/jest.setup.js'],
  transformIgnorePatterns: [
    'node_modules/(?!(jest-)?react-native|@react-native(-community)?|react-native-reanimated|react-native-worklets|@react-navigation|react-native-safe-area-context|react-native-screens|react-native-gesture-handler|@react-native-async-storage|react-native-audio-api|axios)/',
  ],
};