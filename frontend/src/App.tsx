import React, { useEffect, useState, useCallback } from 'react';
import { api } from './api/client';
import { Header } from './components/Header';
import { DiagnosticsPage } from './pages/DiagnosticsPage';
import { LayoutStudio } from './pages/LayoutStudio';
import { CaptionStudio } from './pages/CaptionStudio';
import { StudioWorkbench } from './pages/StudioWorkbench';
import { ExportWorkbench } from './pages/ExportWorkbench';
import {
  CacheStatsResponse,
  SettingsRead,
  SystemDiagnosticsResponse,
} from './types/diagnostics';
import { AlertCircle, RefreshCw } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'diagnostics' | 'studio' | 'layout' | 'captions' | 'exports'>('diagnostics');
  const [diagnostics, setDiagnostics] = useState<SystemDiagnosticsResponse | null>(null);
  const [settings, setSettings] = useState<SettingsRead | null>(null);
  const [cacheStats, setCacheStats] = useState<CacheStatsResponse | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Parallel initial fetch: eliminates waterfalls (vercel-react-best-practices)
  const loadData = useCallback(async (refreshing = false) => {
    if (refreshing) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const [diagRes, settingsRes, cacheRes] = await Promise.all([
        api.getDiagnostics(),
        api.getSettings(),
        api.getCacheStats(),
      ]);

      setDiagnostics(diagRes);
      setSettings(settingsRes);
      setCacheStats(cacheRes);
    } catch (err: any) {
      console.error('Failed to load application telemetry:', err);
      setError(err.message || 'Failed to connect to backend server');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="min-h-screen bg-background text-slate-100 flex flex-col font-sans">
      <Header
        diagnostics={diagnostics}
        settings={settings}
        isRefreshing={isRefreshing}
        onRefresh={() => loadData(true)}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      <main className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3">
            <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
            <p className="text-sm font-mono text-slate-400">Scanning GPU, FFmpeg, Ollama, and JS runtimes...</p>
          </div>
        ) : error ? (
          <div className="max-w-md mx-auto p-6 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-200 space-y-3 font-mono text-xs">
            <div className="flex items-center gap-2 font-bold text-sm text-rose-400">
              <AlertCircle className="w-4 h-4" />
              <span>Backend Connection Error</span>
            </div>
            <p>{error}</p>
            <button
              onClick={() => loadData()}
              className="mt-2 px-4 py-2 rounded-lg bg-rose-500 hover:bg-rose-400 text-black font-semibold transition-all"
            >
              Retry Connection
            </button>
          </div>
        ) : activeTab === 'diagnostics' ? (
          <DiagnosticsPage
            diagnostics={diagnostics}
            settings={settings}
            cacheStats={cacheStats}
            onRefresh={() => loadData(true)}
            onSettingsUpdated={setSettings}
            onCacheCleaned={setCacheStats}
          />
        ) : activeTab === 'layout' ? (
          <LayoutStudio />
        ) : activeTab === 'captions' ? (
          <CaptionStudio />
        ) : activeTab === 'exports' ? (
          <ExportWorkbench />
        ) : (
          <StudioWorkbench />
        )}
      </main>
    </div>
  );
};

export default App;
