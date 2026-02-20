/**
 * useTokenHighlighter - Decoupled token parsing hook.
 *
 * Parses input string, detects @handle and /command tokens,
 * classifies them (known/unknown/incomplete), and returns
 * annotated segments for rendering.
 *
 * N3 Fix (Decoupling): This hook is a pure text parser that works
 * with ANY text input - not coupled to RichChatInput or any
 * specific component.
 *
 * Usage:
 * - RichChatInput (main chat) — mirror div rendering
 * - CustomCommandsSection (flyout) — command body textarea highlighting
 * - Any future text input that needs token awareness
 *
 * The hook does NOT handle DOM manipulation, cursor management, or
 * event handling — those are the responsibility of the consuming component.
 */

import { useMemo } from 'react';

export type TokenType = 'plain' | 'handle' | 'command';
export type TokenStatus = 'known' | 'unknown' | 'incomplete';

export interface TokenSegment {
  text: string;
  type: TokenType;
  status: TokenStatus;
}

export interface UseTokenHighlighterOptions {
  /** The input text to parse */
  text: string;
  /** List of known @handles (without @ prefix) from AppState contacts */
  knownHandles: string[];
  /** List of known command names (without / prefix) from AppState commands */
  knownCommands: string[];
}

/**
 * Parse text and return annotated token segments.
 *
 * Detection rules:
 * - @handle: starts with @, followed by lowercase letters, numbers, hyphens
 * - /command: starts with /, followed by lowercase letters, numbers, hyphens
 * - Status is "incomplete" if token is just the prefix (@ or /) with nothing after
 * - Status is "known" if token matches a known handle/command
 * - Status is "unknown" if token doesn't match any known handle/command
 */
export function useTokenHighlighter({
  text,
  knownHandles,
  knownCommands,
}: UseTokenHighlighterOptions): TokenSegment[] {
  return useMemo(() => {
    if (!text) return [];

    const segments: TokenSegment[] = [];
    const handleSet = new Set(knownHandles.map((h) => h.toLowerCase()));
    const commandSet = new Set(knownCommands.map((c) => c.toLowerCase()));

    // Regex to find @handles and /commands
    // Matches: @handle-name or /command-name (word boundaries matter)
    const tokenRegex = /(@[a-z0-9-]*|\/[a-z0-9-]*)/gi;

    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = tokenRegex.exec(text)) !== null) {
      const matchStart = match.index;
      const matchEnd = matchStart + match[0].length;

      // Add plain text before this match
      if (matchStart > lastIndex) {
        segments.push({
          text: text.slice(lastIndex, matchStart),
          type: 'plain',
          status: 'known',
        });
      }

      const tokenText = match[0];
      const isHandle = tokenText.startsWith('@');
      const isCommand = tokenText.startsWith('/');

      if (isHandle) {
        const handleName = tokenText.slice(1).toLowerCase();
        const status: TokenStatus =
          handleName.length === 0
            ? 'incomplete'
            : handleSet.has(handleName)
              ? 'known'
              : 'unknown';

        segments.push({
          text: tokenText,
          type: 'handle',
          status,
        });
      } else if (isCommand) {
        const commandName = tokenText.slice(1).toLowerCase();
        const status: TokenStatus =
          commandName.length === 0
            ? 'incomplete'
            : commandSet.has(commandName)
              ? 'known'
              : 'unknown';

        segments.push({
          text: tokenText,
          type: 'command',
          status,
        });
      }

      lastIndex = matchEnd;
    }

    // Add remaining plain text
    if (lastIndex < text.length) {
      segments.push({
        text: text.slice(lastIndex),
        type: 'plain',
        status: 'known',
      });
    }

    return segments;
  }, [text, knownHandles, knownCommands]);
}

export default useTokenHighlighter;
