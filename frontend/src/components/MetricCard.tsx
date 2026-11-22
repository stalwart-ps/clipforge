import React, { ReactNode } from 'react';

interface MetricCardProps {
  title: string;
  subtitle?: string;
  icon: ReactNode;
  headerAction?: ReactNode;
  children: ReactNode;
  className?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  subtitle,
  icon,
  headerAction,
  children,
  className = '',
}) => {
  return (
    <div className={`bg-surface border border-border rounded-xl p-5 transition-all hover:border-slate-700 ${className}`}>
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-surface-elevated text-cyan-400 border border-border-subtle">
            {icon}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100 tracking-tight">{title}</h3>
            {subtitle && <p className="text-xs text-slate-400 font-mono mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {headerAction && <div>{headerAction}</div>}
      </div>
      <div>{children}</div>
    </div>
  );
};
