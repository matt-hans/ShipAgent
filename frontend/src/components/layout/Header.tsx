/**
 * Header component - Global navigation and status bar.
 *
 * Features:
 * - Logo and branding
 * - Global status indicators (connection, active job)
 * - Quick actions (new job, settings)
 */

import { useAppState } from '@/hooks/useAppState';
import { cn } from '@/lib/utils';

// Icons
function ShipIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M3 17l1.5-4.5h15L21 17" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4.5 12.5V7a1 1 0 011-1h13a1 1 0 011 1v5.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 17v5M8 22h8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="2" />
    </svg>
  );
}

function StatusDot({ status }: { status: 'connected' | 'disconnected' | 'processing' }) {
  return (
    <span
      className={cn(
        'inline-block w-2 h-2 rounded-full',
        status === 'connected' && 'bg-success pulse-glow',
        status === 'disconnected' && 'bg-slate-500',
        status === 'processing' && 'bg-amber-500 animate-pulse'
      )}
    />
  );
}

export function Header() {
  const { dataSource, activeJob, isProcessing } = useAppState();

  const connectionStatus = dataSource?.status === 'connected' ? 'connected' : 'disconnected';
  const jobStatus = isProcessing ? 'processing' : activeJob ? 'connected' : 'disconnected';

  return (
    <header className="app-header">
      {/* Gradient accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-amber-500/50 to-transparent" />

      <div className="container-wide h-14 flex items-center justify-between">
        {/* Left: Logo and branding */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-amber-500 to-amber-600 flex items-center justify-center shadow-lg">
                <ShipIcon className="w-5 h-5 text-void-950" />
              </div>
              {/* Live indicator */}
              {(dataSource || isProcessing) && (
                <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-success rounded-full border-2 border-void-950 pulse-glow" />
              )}
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-tight text-slate-100">
                ShipAgent
              </h1>
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                Command Center
              </p>
            </div>
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-slate-800" />

          {/* Status badges */}
          <div className="flex items-center gap-3">
            {/* Data source status */}
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-slate-800/50 border border-slate-700/50">
              <StatusDot status={connectionStatus} />
              <span className="text-xs font-mono text-slate-400">
                {dataSource ? (
                  <span>
                    <span className="text-slate-300">{dataSource.type.toUpperCase()}</span>
                    {dataSource.row_count && (
                      <span className="text-slate-500"> · {dataSource.row_count.toLocaleString()} rows</span>
                    )}
                  </span>
                ) : (
                  'No data source'
                )}
              </span>
            </div>

            {/* Active job status */}
            {activeJob && (
              <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-slate-800/50 border border-slate-700/50">
                <StatusDot status={jobStatus} />
                <span className="text-xs font-mono text-slate-400">
                  <span className="text-slate-300">Job</span>
                  <span className="text-slate-500"> · {activeJob.status}</span>
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Right: Version indicator */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-slate-600 px-2 py-1 rounded bg-slate-800/30 border border-slate-700/30">
            v1.0.0
          </span>
        </div>
      </div>
    </header>
  );
}

export default Header;
