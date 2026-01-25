/**
 * CommandHistory component for displaying recent commands.
 *
 * Shows a list of recent commands that users can click to reuse,
 * with status badges and timestamps.
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
 * Status badge styles by job status.
 */
const STATUS_STYLES: Record<JobStatus, { bg: string; text: string; label: string }> = {
  pending: {
    bg: 'bg-gray-100 dark:bg-gray-800',
    text: 'text-gray-700 dark:text-gray-300',
    label: 'Pending',
  },
  running: {
    bg: 'bg-blue-100 dark:bg-blue-900/40',
    text: 'text-blue-700 dark:text-blue-300',
    label: 'Running',
  },
  paused: {
    bg: 'bg-yellow-100 dark:bg-yellow-900/40',
    text: 'text-yellow-700 dark:text-yellow-300',
    label: 'Paused',
  },
  completed: {
    bg: 'bg-green-100 dark:bg-green-900/40',
    text: 'text-green-700 dark:text-green-300',
    label: 'Complete',
  },
  failed: {
    bg: 'bg-red-100 dark:bg-red-900/40',
    text: 'text-red-700 dark:text-red-300',
    label: 'Failed',
  },
  cancelled: {
    bg: 'bg-gray-100 dark:bg-gray-800',
    text: 'text-gray-500 dark:text-gray-400',
    label: 'Cancelled',
  },
};

/**
 * Status badge component.
 */
function StatusBadge({ status }: { status: JobStatus }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.pending;

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
        style.bg,
        style.text
      )}
    >
      {style.label}
    </span>
  );
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
      className={cn('h-3 w-3', className)}
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

/**
 * Reuse/refresh icon.
 */
function ReuseIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('h-4 w-4', className)}
    >
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
      <path d="M8 16H3v5" />
    </svg>
  );
}

/**
 * CommandHistory displays recent commands with click-to-reuse functionality.
 *
 * Features:
 * - Shows up to 5 most recent commands
 * - Status badge for each command
 * - Relative timestamp (e.g., "2h ago")
 * - Click to populate command input
 * - Hover state reveals reuse action
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
      <Card className={cn('w-full', className)}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">Recent Commands</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 rounded-lg bg-muted/50 animate-pulse"
              />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (displayCommands.length === 0) {
    return (
      <Card className={cn('w-full', className)}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">Recent Commands</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-6">
            No commands yet. Enter a command above to get started.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={cn('w-full', className)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-medium">Recent Commands</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {displayCommands.map((item) => (
          <button
            key={item.id}
            onClick={() => onSelect(item.command)}
            className={cn(
              'w-full text-left p-3 rounded-lg',
              'bg-muted/30 hover:bg-muted/60',
              'border border-transparent hover:border-border/50',
              'transition-all duration-200',
              'group',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
            )}
            type="button"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                {/* Command text - truncated with ellipsis */}
                <p className="text-sm font-medium truncate text-foreground group-hover:text-primary transition-colors">
                  {item.command}
                </p>
                {/* Metadata row */}
                <div className="flex items-center gap-3 mt-1.5">
                  <StatusBadge status={item.status} />
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <ClockIcon />
                    {formatRelativeTime(item.created_at)}
                  </span>
                </div>
              </div>
              {/* Reuse indicator - visible on hover */}
              <div className={cn(
                'flex items-center gap-1 text-xs text-muted-foreground',
                'opacity-0 group-hover:opacity-100 transition-opacity',
                'shrink-0'
              )}>
                <ReuseIcon />
                <span>Reuse</span>
              </div>
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

export default CommandHistory;
