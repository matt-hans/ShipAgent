/**
 * Collapsible chip showing an active agent tool call.
 */

import type { ConversationEvent } from '@/hooks/useConversation';
import { GearIcon } from '@/components/ui/icons';

/** Collapsible chip showing an agent tool call. */
export function ToolCallChip({ event }: { event: ConversationEvent }) {
  const toolName = (event.data.tool_name as string) || 'tool';
  const label = toolName
    .replace(/^mcp__\w+__/, '')
    .replace(/_tool$/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/10 to-cyan-600/10 border border-cyan-500/20 flex items-center justify-center">
        <GearIcon className="w-3.5 h-3.5 text-cyan-400/60" />
      </div>
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/50 border border-slate-700/50">
        <span className="w-2 h-2 rounded-full bg-cyan-400/50 animate-pulse" />
        <span className="text-[11px] font-mono text-slate-400">{label}</span>
      </div>
    </div>
  );
}
