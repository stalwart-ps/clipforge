import React from 'react';
import { Cpu, RefreshCw, Sparkles, Scissors } from 'lucide-react';
import { SettingsRead, SystemDiagnosticsResponse } from '../types/diagnostics';

interface HeaderProps {
  diagnostics: SystemDiagnosticsResponse | null;
  settings: SettingsRead | null;
  isRefreshing: boolean;
  onRefresh: () => void;
  activeTab: 'diagnostics' | 'studio' | 'layout' | 'captions' | 'exports';
  onTabChange: (tab: 'diagnostics' | 'studio' | 'layout' | 'captions' | 'exports') => void;
}

export const Header: React.FC<HeaderProps> = ({
  diagnostics,
  settings,
  isRefreshing,
  onRefresh,
  activeTab,
  onTabChange,
}) => {
  return (
    <header className="border-b border-border bg-surface/90 backdrop-blur-md sticky top-0 z-50 px-6 py-3.5">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* Logo & App Title */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-black font-black text-sm shadow-lg shadow-cyan-500/20">
              CF
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-100 tracking-tight text-base">ClipForge</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-cyan-950/80 text-cyan-400 border border-cyan-800/60 font-mono">
                  LOCAL
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-mono">100% Offline AI Video Studio</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="hidden md:flex items-center gap-1 bg-surface-elevated p-1 rounded-lg border border-border-subtle">
            <button
              onClick={() => onTabChange('diagnostics')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                activeTab === 'diagnostics'
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Hardware & Settings
            </button>
            <button
              onClick={() => onTabChange('studio')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'studio'
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
              Studio Workbench
              <span className="text-[9px] px-1 py-0.2 rounded bg-cyan-950 text-cyan-400 border border-cyan-800">
                Phase 2
              </span>
            </button>
            <button
              onClick={() => onTabChange('layout')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                activeTab === 'layout'
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Layout Studio
            </button>
            <button
              onClick={() => onTabChange('captions')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                activeTab === 'captions'
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Caption Studio
            </button>
            <button
              onClick={() => onTabChange('exports')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'exports'
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Scissors className="w-3.5 h-3.5" />
              Clip Workbench
            </button>
          </nav>
        </div>

        {/* Telemetry Status Glance & Refresh */}
        <div className="flex items-center gap-3">
          {/* Active Preset Badge */}
          {settings && (
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-surface-elevated border border-border text-xs font-mono text-slate-300">
              <Cpu className="w-3.5 h-3.5 text-cyan-400" />
              <span>Preset:</span>
              <span className="text-cyan-400 font-semibold uppercase">{settings.hardwarePreset}</span>
            </div>
          )}

          {/* GPU VRAM status pill */}
          {diagnostics?.gpu.hasGpu && (
            <div className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-md bg-surface-elevated border border-border text-xs font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]" />
              <span className="text-slate-300">{diagnostics.gpu.gpuName?.split(' ')[1] || 'GPU'}</span>
              <span className="text-emerald-400">
                {diagnostics.gpu.vramUsedMb}/{diagnostics.gpu.vramTotalMb} MB
              </span>
            </div>
          )}

          {/* Manual Refresh Button */}
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-surface-elevated hover:bg-surface-hover active:scale-95 border border-border text-xs font-medium text-slate-300 transition-all disabled:opacity-50"
            title="Re-run hardware & service telemetry checks"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-cyan-400' : 'text-slate-400'}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>
    </header>
  );
};
