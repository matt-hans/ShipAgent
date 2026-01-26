/**
 * CommandInput component for natural language shipping commands.
 *
 * Industrial Terminal aesthetic - command-line interface inspired
 * input with technical details and shipping example chips.
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

export interface CommandInputProps {
  /** Callback when command is submitted. */
  onSubmit: (command: string) => Promise<void>;
  /** Whether the input is disabled (e.g., during submission). */
  disabled?: boolean;
  /** Optional additional class name. */
  className?: string;
}

/**
 * Example commands shown as clickable chips.
 */
const EXAMPLE_COMMANDS = [
  'Ship all California orders using UPS Ground',
  "Ship today's orders from orders.csv with UPS 2nd Day Air",
  'Create shipments for all pending orders to Texas',
];

/**
 * Loading spinner icon.
 */
function LoadingSpinner({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      className={cn('animate-spin', className)}
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

/**
 * Send icon for submit button.
 */
function SendIcon({ className }: { className?: string }) {
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
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

/**
 * Terminal cursor icon.
 */
function TerminalIcon({ className }: { className?: string }) {
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
      <polyline points="5 9 9 5 5 1" />
      <line x1="9" y1="5" x2="19" y2="5" />
    </svg>
  );
}

/**
 * CommandInput allows users to enter natural language shipping commands.
 *
 * Features:
 * - Large terminal-style input with grid background
 * - Submit on Enter key or button click
 * - Loading state during submission
 * - Example command chips styled as terminal commands
 * - Keyboard accessible with industrial aesthetic
 */
export function CommandInput({ onSubmit, disabled = false, className }: CommandInputProps) {
  const [command, setCommand] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleSubmit = async () => {
    const trimmed = command.trim();
    if (!trimmed || isSubmitting || disabled) return;

    setIsSubmitting(true);
    try {
      await onSubmit(trimmed);
      setCommand(''); // Clear on success
    } finally {
      setIsSubmitting(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleExampleClick = (example: string) => {
    setCommand(example);
    inputRef.current?.focus();
  };

  const isDisabled = disabled || isSubmitting;
  const canSubmit = command.trim().length > 0 && !isDisabled;

  return (
    <div className={cn('space-y-5', className)}>
      {/* Main input row */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          {/* Terminal prompt icon */}
          <div className="absolute left-3 top-1/2 -translate-y-1/2 z-10 text-signal-500">
            <TerminalIcon className="h-4 w-4" />
          </div>

          <Input
            ref={inputRef}
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ship all California orders using UPS Ground..."
            disabled={isDisabled}
            className={cn(
              'h-14 text-base pr-4 pl-10',
              'input-terminal',
              'font-mono-display',
              'placeholder:text-steel-500',
              'focus-visible:ring-2 focus-visible:ring-signal-500/50 focus-visible:border-signal-500',
              isDisabled && 'opacity-60'
            )}
            aria-label="Shipping command input"
          />

          {/* Character count indicator */}
          {command.length > 0 && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 font-mono-display text-[10px] text-steel-500">
              {command.length} CHARS
            </div>
          )}
        </div>

        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          size="lg"
          className={cn(
            'h-14 px-6 gap-2 font-mono-display text-sm uppercase tracking-wider',
            'transition-all duration-200',
            'btn-industrial',
            canSubmit && 'hover:shadow-lg hover:shadow-signal-500/20'
          )}
        >
          {isSubmitting ? (
            <>
              <LoadingSpinner className="h-4 w-4" />
              <span>PROCESSING</span>
            </>
          ) : (
            <>
              <SendIcon className="h-4 w-4" />
              <span>EXECUTE</span>
            </>
          )}
        </Button>
      </div>

      {/* Example commands */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <div className="h-px flex-1 bg-steel-700/50" />
          <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-widest">
            Quick Commands
          </p>
          <div className="h-px flex-1 bg-steel-700/50" />
        </div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_COMMANDS.map((example, index) => (
            <button
              key={index}
              onClick={() => handleExampleClick(example)}
              disabled={isDisabled}
              className={cn(
                'group relative text-xs px-4 py-2 rounded-sm font-mono-display',
                'bg-warehouse-800 text-steel-300',
                'border border-steel-700',
                'transition-all duration-200',
                'hover:bg-warehouse-700 hover:border-signal-500/50 hover:text-signal-500',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/50',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                // Terminal-style corner accents
                'before:absolute before:top-0 before:left-0 before:w-1.5 before:h-1.5 before:border-t before:border-l before:border-steel-600',
                'after:absolute after:bottom-0 after:right-0 after:w-1.5 after:h-1.5 after:border-b after:border-r after:border-steel-600',
                'group-hover:before:border-signal-500 group-hover:after:border-signal-500'
              )}
              type="button"
            >
              <span className="relative z-10">{example}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Technical footer */}
      <div className="flex items-center justify-between pt-2">
        <div className="flex items-center gap-4 font-mono-display text-[10px] text-steel-600 uppercase tracking-wider">
          <span>NL Interface v1.0</span>
          <span>::</span>
          <span>UPS Connected</span>
        </div>
        <div className="font-mono-display text-[10px] text-steel-600">
          PRESS ENTER TO EXECUTE
        </div>
      </div>
    </div>
  );
}

export default CommandInput;
