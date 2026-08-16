/**
 * Central app state — a single lightweight reducer + context. Holds the
 * server URL, current model, connection state and preferences, persisting
 * only what needs to survive restarts (server URL + model + preferences).
 *
 * Deliberately framework-free: scaling is done by splitting selectors /
 * effects, not by pulling in a heavier state library.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useState,
} from 'react';

import { STORAGE_KEYS } from '../config';
import { ApiError, getMobileStatus } from '../services/api';
import {
  loadServerUrl,
  setServerUrl as persistServerUrl,
} from '../services/serverConfig';
import { getJSON, setJSON } from '../services/storage';
import type {
  ConnectionState,
  MobileStatus,
  Preferences,
} from '../types';
import { DEFAULT_PREFERENCES } from '../types';

interface AppState {
  serverUrl: string;
  /** null until the first status probe completes. */
  status: MobileStatus | null;
  connection: ConnectionState;
  model: string;
  preferences: Preferences;
  /** True once persisted values have been restored from storage. */
  isHydrated: boolean;
}

type Action =
  | { type: 'SET_SERVER'; url: string }
  | { type: 'SET_STATUS'; status: MobileStatus | null }
  | { type: 'SET_CONNECTION'; connection: ConnectionState }
  | { type: 'SET_MODEL'; model: string }
  | { type: 'SET_PREFERENCES'; preferences: Preferences }
  | { type: 'SET_HYDRATED'; hydrated: boolean };

const initialState: AppState = {
  serverUrl: '',
  status: null,
  connection: 'unknown',
  model: '',
  preferences: DEFAULT_PREFERENCES,
  isHydrated: false,
};

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'SET_SERVER':
      return { ...state, serverUrl: action.url };
    case 'SET_STATUS':
      return { ...state, status: action.status };
    case 'SET_CONNECTION':
      return { ...state, connection: action.connection };
    case 'SET_MODEL':
      return { ...state, model: action.model };
    case 'SET_PREFERENCES':
      return { ...state, preferences: action.preferences };
    case 'SET_HYDRATED':
      return { ...state, isHydrated: action.hydrated };
    default:
      return state;
  }
}

export interface AppContextValue {
  state: AppState;
  setServerUrl: (url: string) => Promise<void>;
  setModel: (model: string) => Promise<void>;
  updatePreferences: (patch: Partial<Preferences>) => Promise<void>;
  refreshStatus: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [probeToken, setProbeToken] = useState(0);

  // Hydrate persisted server URL, model and preferences once.
  useEffect(() => {
    let active = true;
    (async () => {
      const url = await loadServerUrl();
      const model = await getJSON<string>(STORAGE_KEYS.model);
      const preferences = await getJSON<Preferences>(STORAGE_KEYS.preferences);
      if (!active) {
        return;
      }
      dispatch({ type: 'SET_SERVER', url });
      dispatch({
        type: 'SET_MODEL',
        model: model && model.length ? model : '',
      });
      if (preferences) {
        dispatch({
          type: 'SET_PREFERENCES',
          preferences: { ...DEFAULT_PREFERENCES, ...preferences },
        });
      }
      dispatch({ type: 'SET_HYDRATED', hydrated: true });
    })();
    return () => {
      active = false;
    };
  }, []);

  // Probe mobile status whenever the server URL changes.
  useEffect(() => {
    if (!state.serverUrl) {
      return;
    }
    let active = true;
    const token = probeToken;
    dispatch({ type: 'SET_CONNECTION', connection: 'connecting' });
    (async () => {
      try {
        const status = await getMobileStatus();
        if (!active || token !== probeToken) {
          return;
        }
        dispatch({ type: 'SET_STATUS', status });
        dispatch({ type: 'SET_CONNECTION', connection: 'connected' });
        if (!state.model) {
          dispatch({ type: 'SET_MODEL', model: status.model });
        }
      } catch (error) {
        if (!active || token !== probeToken) {
          return;
        }
        dispatch({ type: 'SET_STATUS', status: null });
        dispatch({ type: 'SET_CONNECTION', connection: 'error' });
        if (error instanceof ApiError && error.code === 'network') {
          // Surface for UI; persisted state is preserved.
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [state.serverUrl, probeToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const setServerUrl = useCallback(async (url: string) => {
    await persistServerUrl(url);
    dispatch({ type: 'SET_SERVER', url });
    setProbeToken((t) => t + 1);
  }, []);

  const setModel = useCallback(async (model: string) => {
    dispatch({ type: 'SET_MODEL', model });
    await setJSON(STORAGE_KEYS.model, model);
  }, []);

  const updatePreferences = useCallback(
    async (patch: Partial<Preferences>) => {
      const next = { ...state.preferences, ...patch };
      await setJSON(STORAGE_KEYS.preferences, next);
      dispatch({ type: 'SET_PREFERENCES', preferences: next });
    },
    [state.preferences],
  );

  const refreshStatus = useCallback(async () => {
    setProbeToken((t) => t + 1);
  }, []);

  const value = useMemo<AppContextValue>(
    () => ({
      state,
      setServerUrl,
      setModel,
      updatePreferences,
      refreshStatus,
    }),
    [state, setServerUrl, setModel, updatePreferences, refreshStatus],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider.');
  }
  return context;
}