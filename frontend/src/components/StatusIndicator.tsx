import React from 'react';

interface StatusIndicatorProps {
  status:
    | 'optimal'
    | 'ready'
    | 'connected'
    | 'high_usage'
    | 'warning'
    | 'warning_no_js'
    | 'ready_cpu_only'
    | 'disconnected'
    | 'missing'
    | 'not_detected'
    | 'error'
    | 'empty';
  label?: string;
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({ status, label }) => {
  let color = 'bg-slate-500';
  let textColor = 'text-slate-400';
  let defaultLabel: string = status;

  switch (status) {
    case 'optimal':
    case 'ready':
    case 'connected':
      color = 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]';
      textColor = 'text-emerald-400';
      defaultLabel = status === 'connected' ? 'Connected' : 'Ready';
      break;
    case 'ready_cpu_only':
      color = 'bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.4)]';
      textColor = 'text-cyan-400';
      defaultLabel = 'CPU Only (libx264)';
      break;
    case 'high_usage':
    case 'warning':
    case 'warning_no_js':
      color = 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.4)]';
      textColor = 'text-amber-400';
      defaultLabel = status === 'warning_no_js' ? 'No JS Runtime' : 'High Usage';
      break;
    case 'empty':
      color = 'bg-amber-400';
      textColor = 'text-amber-300';
      defaultLabel = 'No Models';
      break;
    case 'disconnected':
    case 'missing':
    case 'not_detected':
    case 'error':
      color = 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.4)]';
      textColor = 'text-rose-400';
      defaultLabel = status === 'not_detected' ? 'Not Detected' : (status === 'disconnected' ? 'Offline' : 'Missing');
      break;
  }

  return (
    <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-surface-elevated border border-border text-xs font-mono">
      <span className={`w-2 h-2 rounded-full ${color}`} />
      <span className={textColor}>{label || defaultLabel}</span>
    </div>
  );
};
