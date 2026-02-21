/**
 * Visual timeline minimap for chat navigation.
 *
 * Thin vertical line with color-coded dots representing messages.
 * Syncs with scroll position via IntersectionObserver.
 * Click a dot to scroll to the corresponding message.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { ConversationMessage } from '@/hooks/useAppState';

/** Map message to timeline dot color. */
function getDotColor(message: ConversationMessage): string {
  if (message.metadata?.action === 'error') return 'bg-red-400';
  if (message.metadata?.action) return 'bg-amber-400'; // artifact
  if (message.role === 'user') return 'bg-slate-400';
  return 'bg-cyan-400'; // assistant
}

/**
 * Collapse system text messages that immediately precede an artifact into
 * the artifact's dot. This prevents duplicate dots for a single visual block
 * (e.g. "Batch confirmed..." text + CompletionArtifact card).
 */
function deduplicateForTimeline(msgs: ConversationMessage[]): ConversationMessage[] {
  const result: ConversationMessage[] = [];
  for (let i = 0; i < msgs.length; i++) {
    const curr = msgs[i];
    const next = msgs[i + 1];
    // Skip non-artifact system messages that are immediately followed by an artifact
    if (
      curr.role === 'system' &&
      !curr.metadata?.action &&
      next?.role === 'system' &&
      next.metadata?.action &&
      next.metadata.action !== 'error'
    ) {
      continue;
    }
    result.push(curr);
  }
  return result;
}

interface ChatTimelineProps {
  messages: ConversationMessage[];
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
}

export function ChatTimeline({ messages, scrollContainerRef }: ChatTimelineProps) {
  const timelineDots = React.useMemo(() => deduplicateForTimeline(messages), [messages]);
  const [visibleIds, setVisibleIds] = React.useState<Set<string>>(new Set());

  // Observe which messages are in the viewport
  React.useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        setVisibleIds((prev) => {
          const next = new Set(prev);
          for (const entry of entries) {
            const id = entry.target.getAttribute('data-message-id');
            if (!id) continue;
            if (entry.isIntersecting) next.add(id);
            else next.delete(id);
          }
          return next;
        });
      },
      { root: container, threshold: 0.3 },
    );

    const elements = container.querySelectorAll('[data-message-id]');
    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [scrollContainerRef, messages.length]);

  const handleDotClick = (messageId: string) => {
    const el = scrollContainerRef.current?.querySelector(
      `[data-message-id="${messageId}"]`,
    );
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  if (messages.length === 0) return null;

  return (
    <div className="relative w-4 flex-shrink-0 flex flex-col items-center py-6">
      {/* Vertical line */}
      <div className="absolute top-6 bottom-6 w-px bg-slate-800" />

      {/* Dots */}
      <div className="relative flex flex-col justify-between h-full w-full items-center">
        {timelineDots.map((msg) => {
          const isVisible = visibleIds.has(msg.id);
          return (
            <button
              key={msg.id}
              onClick={() => handleDotClick(msg.id)}
              className={cn(
                'relative z-10 rounded-full transition-all duration-200 cursor-pointer',
                getDotColor(msg),
                isVisible ? 'w-2.5 h-2.5 opacity-100 shadow-lg' : 'w-1.5 h-1.5 opacity-50',
              )}
              title={`${msg.role}: ${msg.content.slice(0, 40)}...`}
            />
          );
        })}
      </div>
    </div>
  );
}
