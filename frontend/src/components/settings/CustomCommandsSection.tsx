/**
 * Custom Commands Section - Settings accordion section.
 *
 * Shows saved command count with expandable list and inline editor.
 * Full inline editing functionality will be added in Task 13.
 */

import { ChevronDown, Terminal, Plus, ExternalLink } from 'lucide-react';
import { useAppState } from '@/hooks/useAppState';

interface CustomCommandsSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function CustomCommandsSection({
  isOpen,
  onToggle,
}: CustomCommandsSectionProps) {
  const { customCommands } = useAppState();

  return (
    <div className="settings-section">
      <button
        className="settings-section-header"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-foreground">Custom Commands</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {customCommands.length} commands
          </span>
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${
              isOpen ? 'rotate-180' : ''
            }`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-3">
          {/* Command list preview */}
          {customCommands.length > 0 && (
            <div className="space-y-1">
              {customCommands.slice(0, 3).map((cmd) => (
                <div
                  key={cmd.id}
                  className="flex items-center justify-between px-2 py-1.5 rounded bg-muted/50"
                >
                  <code className="text-xs font-mono text-foreground">
                    /{cmd.name}
                  </code>
                  <span className="text-xs text-muted-foreground truncate max-w-[120px]">
                    {cmd.description || cmd.body.slice(0, 30)}
                  </span>
                </div>
              ))}
              {customCommands.length > 3 && (
                <p className="text-xs text-muted-foreground text-center">
                  +{customCommands.length - 3} more
                </p>
              )}
            </div>
          )}

          {/* Empty state */}
          {customCommands.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-2">
              No custom commands yet. Create shortcuts for common shipping instructions.
            </p>
          )}

          {/* Manage commands button */}
          <button
            className="w-full flex items-center justify-between px-3 py-2 rounded-md bg-muted hover:bg-muted/80 transition-colors"
          >
            <span className="text-sm text-foreground">Manage commands</span>
            <ExternalLink className="h-4 w-4 text-muted-foreground" />
          </button>

          {/* Add command button */}
          <button
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md border border-dashed border-border hover:border-primary hover:bg-primary/5 transition-colors"
          >
            <Plus className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Create new command</span>
          </button>
        </div>
      )}
    </div>
  );
}

export default CustomCommandsSection;
