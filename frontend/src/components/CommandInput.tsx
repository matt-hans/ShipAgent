/**
 * CommandInput component for natural language shipping commands.
 *
 * Provides a text input with submit functionality and example command chips
 * for quick command population.
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
  'Ship today\'s orders from orders.csv with UPS 2nd Day Air',
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
      className={cn('h-4 w-4 animate-spin', className)}
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
      className={cn('h-4 w-4', className)}
    >
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

/**
 * CommandInput allows users to enter natural language shipping commands.
 *
 * Features:
 * - Large text input with descriptive placeholder
 * - Submit on Enter key or button click
 * - Loading state during submission
 * - Example command chips for quick population
 * - Keyboard accessible
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
    <div className={cn('space-y-4', className)}>
      {/* Main input row */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Input
            ref={inputRef}
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ship all California orders using UPS Ground..."
            disabled={isDisabled}
            className={cn(
              'h-12 text-base pr-4',
              'placeholder:text-muted-foreground/70',
              'focus-visible:ring-2 focus-visible:ring-primary/50',
              isDisabled && 'opacity-60'
            )}
            aria-label="Shipping command input"
          />
        </div>
        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          size="lg"
          className={cn(
            'h-12 px-6 gap-2',
            'transition-all duration-200',
            canSubmit && 'hover:scale-[1.02] active:scale-[0.98]'
          )}
        >
          {isSubmitting ? (
            <>
              <LoadingSpinner />
              <span>Processing...</span>
            </>
          ) : (
            <>
              <SendIcon />
              <span>Submit</span>
            </>
          )}
        </Button>
      </div>

      {/* Example commands */}
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
          Try an example
        </p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_COMMANDS.map((example, index) => (
            <button
              key={index}
              onClick={() => handleExampleClick(example)}
              disabled={isDisabled}
              className={cn(
                'text-sm px-3 py-1.5 rounded-full',
                'bg-secondary text-secondary-foreground',
                'border border-border/50',
                'transition-all duration-200',
                'hover:bg-accent hover:text-accent-foreground hover:border-border',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
              type="button"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default CommandInput;
