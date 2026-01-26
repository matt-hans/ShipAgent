/**
 * CommandHistory component for displaying recent commands.
 *
 * Industrial Terminal aesthetic - command log panel style
 * with technical details and monospace typography.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { CommandHistoryItem, JobStatus } from '@/types/api';

export interface CommandHistoryProps {
  /** List of recent commands. */
  commands: CommandHistoryItem[];
  /** Callback when a command is selected for reuse. */
  onSelect: (command: string) => void;
  /** Whether the history is loading. */
  isLoading?: boolean;
  /** Optional additional class name. */
  className?: string;
}

/**
 * Formats a timestamp string to relative time (e.g., "2 hours ago").
 */
function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;

  return date.toLocaleDateString();
}

/**
 * Status indicator dot by job status.
 */
function getStatusColor(status: JobStatus): string {
  const colors: Record<JobStatus, string> = {
    pending: 'bg-steel-500',
    running: 'bg-route-500 animate-pulse',
    paused: 'bg-status-hold',
    completed: 'bg-status-go',
    failed: 'bg-status-stop',
    cancelled: 'bg-steel-600',
  };
  return colors[status] || colors.pending;
}

/**
 * Clock icon for timestamp.
 */
function ClockIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

/**
 * CommandHistory displays recent commands with click-to-reuse functionality.
 *
 * Features:
 * - Terminal log style display
 * - Status indicator dots
 * - Relative timestamp in monospace
 * - Click to populate command input
 * - Hover state reveals technical details
 */
export function CommandHistory({
  commands,
  onSelect,
  isLoading = false,
  className,
}: CommandHistoryProps) {
  // Show only the 5 most recent
  const displayCommands = commands.slice(0, 5);

  if (isLoading) {
    return (
      <Card className={cn('card-industrial', className)}>
        <CardHeader className="pb-3 border-b border-steel-700/50">
          <CardTitle className="font-display text-sm">
            Command Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 py-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-12 bg-warehouse-800/50 rounded-sm animate-pulse"
                style={{ animationDelay: `${i * 100}ms` }}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (displayCommands.length === 0) {
    return (
      <Card className={cn('card-industrial', className)}>
        <CardHeader className="pb-3 border-b border-steel-700/50">
          <CardTitle className="font-display text-sm">
            Command Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8">
            <p className="font-mono-display text-xs text-steel-500">
              [ NO COMMANDS YET ]
            </p>
            <p className="mt-2 text-sm text-steel-600">
              Enter a command to begin processing
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={cn('card-industrial', className)}>
      <CardHeader className="pb-3 border-b border-steel-700/50">
        <div className="flex items-center justify-between">
          <CardTitle className="font-display text-sm">
            Command Log
          </CardTitle>
          <span className="font-mono-display text-[10px] text-steel-500">
            {displayCommands.length} ENTRIES
          </span>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <div className="divide-y divide-steel-700/50">
          {displayCommands.map((item, index) => (
            <button
              key={item.id}
              onClick={() => onSelect(item.command)}
              className={cn(
                'w-full text-left p-3 transition-all duration-200',
                'hover:bg-warehouse-800/50',
                'focus-visible:outline-none focus-visible:bg-warehouse-800/50',
                'group animate-fade-in',
                `delay-${Math.min(index * 50, 200)}`
              )}
              type="button"
            >
              <div className="flex items-start gap-3">
                {/* Line number */}
                <span className="font-mono-display text-[10px] text-steel-600 w-6 pt-1">
                  {String(index + 1).padStart(2, '0')}
                </span>

                {/* Status indicator */}
                <div className="pt-1">
                  <div className={cn('h-2 w-2 rounded-full', getStatusColor(item.status))} />
                </div>

                {/* Command text and metadata */}
                <div className="flex-1 min-w-0">
                  <p className="font-mono-display text-sm text-steel-200 truncate group-hover:text-signal-500 transition-colors">
                    {item.command}
                  </p>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="font-mono-display text-[10px] text-steel-500 uppercase">
                      {item.status}
                    </span>
                    <span className="text-steel-700">•</span>
                    <span className="flex items-center gap-1 text-[10px] text-steel-600">
                      <ClockIcon className="h-3 w-3" />
                      {formatRelativeTime(item.created_at)}
                    </span>
                  </div>
                </div>

                {/* Arrow indicator on hover */}
                <div className={cn(
                  'opacity-0 group-hover:opacity-100 transition-opacity',
                  'shrink-0 pt-1'
                )}>
                  <svg
                    className="h-4 w-4 text-signal-500"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                  >
                    <polyline points="9 18 15 12 9 12" />
                    <path d="M15 12v-6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              </div>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default CommandHistory;
