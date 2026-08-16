/**
 * @format
 * Smoke-renders the shared component primitives so their imports, theme
 * wiring and JSX compile and mount under the test renderer.
 */

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';

import { AIOrb } from '../src/components/AIOrb';
import { BottomNav } from '../src/components/BottomNav';
import { Glass } from '../src/components/Glass';
import { GlassButton } from '../src/components/GlassButton';
import { StatePill } from '../src/components/StatePill';
import { SuggestionCard } from '../src/components/SuggestionCard';
import { Transcript } from '../src/components/Transcript';
import { Waveform } from '../src/components/Waveform';
import { AI_STATES, type TranscriptMessage } from '../src/types';

const samples: TranscriptMessage[] = [
  { id: '1', role: 'user', text: 'Hello Vyren', final: true },
  { id: '2', role: 'assistant', text: 'Hi there.', final: true },
  { id: '3', role: 'tool', text: 'looked up a file', final: true, toolName: 'read_file' },
];

let mounted: ReactTestRenderer.ReactTestRenderer | null = null;

function render(node: React.ReactElement) {
  let tree!: ReactTestRenderer.ReactTestRenderer;
  ReactTestRenderer.act(() => {
    tree = ReactTestRenderer.create(node);
  });
  mounted = tree;
  return tree;
}

afterEach(() => {
  ReactTestRenderer.act(() => {
    mounted?.unmount();
    mounted = null;
  });
});

test('Glass renders with a translucent fill', () => {
  const tree = render(<Glass level="medium">content</Glass>);
  expect(tree.toJSON()).toBeTruthy();
});

test('Glass blur is opt-in (defaults to non-blurred fill)', () => {
  const plain = render(<Glass>fill</Glass>).toJSON();
  expect(plain).toBeTruthy();
  // BlurView is only mounted when blurred is true.
  const blurred = render(<Glass blurred />).toJSON();
  expect(blurred).toBeTruthy();
});

test('GlassButton renders label and supports variants', () => {
  for (const variant of ['primary', 'secondary', 'ghost', 'danger'] as const) {
    const tree = render(<GlassButton label={variant} variant={variant} />);
    expect(JSON.stringify(tree.toJSON())).toContain(variant);
  }
  const loading = render(<GlassButton label="go" loading />);
  expect(loading.toJSON()).toBeTruthy();
});

test('StatePill resolves labels for every AI state', () => {
  for (const state of AI_STATES) {
    const tree = render(<StatePill state={state} />);
    expect(tree.toJSON()).toBeTruthy();
  }
});

test('SuggestionCard renders resting and selected states', () => {
  render(<SuggestionCard title="Remind me" body="About lunch" />);
  render(<SuggestionCard title="Selected" selected />);
});

test('Transcript renders rows and an empty state', () => {
  const withRows = render(<Transcript messages={samples} />);
  expect(JSON.stringify(withRows.toJSON())).toContain('Hello Vyren');

  const empty = render(<Transcript messages={[]} />);
  expect(empty.toJSON()).toBeTruthy();
});

test('Waveform renders with and without explicit peaks', () => {
  render(<Waveform active />);
  render(<Waveform active peaks={[0.2, 0.5, 0.9, 0.4]} />);
});

test('AIOrb renders for every AI state', () => {
  for (const state of AI_STATES) {
    const tree = render(<AIOrb state={state} active />);
    expect(tree.toJSON()).toBeTruthy();
  }
});

test('BottomNav renders items and active selection', () => {
  const items = [
    { key: 'chats', label: 'Chats' },
    { key: 'live', label: 'Live' },
    { key: 'camera', label: 'Camera' },
    { key: 'vision', label: 'Vision' },
  ];
  const tree = render(<BottomNav items={items} activeKey="live" onSelect={() => {}} />);
  expect(tree.toJSON()).toBeTruthy();
});