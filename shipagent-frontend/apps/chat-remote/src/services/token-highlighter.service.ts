/**
 * TokenHighlighterService — Port of useTokenHighlighter.ts.
 *
 * Parses input text and returns annotated token segments for mirror-div
 * rendering. Classifies @handle and /command tokens as known/unknown/incomplete.
 *
 * Pure text parser — no DOM or Angular DI dependencies.
 * Provided at component level for explicit lifecycle control.
 */

import { Injectable } from '@angular/core';

export type TokenType = 'plain' | 'handle' | 'command';
export type TokenStatus = 'known' | 'unknown' | 'incomplete';

export interface TokenSegment {
  text: string;
  type: TokenType;
  status: TokenStatus;
}

@Injectable()
export class TokenHighlighterService {
  /**
   * Parse text into annotated token segments.
   *
   * Detection rules:
   * - @handle: starts with @, followed by lowercase letters, numbers, hyphens
   * - /command: starts with /, followed by lowercase letters, numbers, hyphens
   * - Status is "incomplete" if token is just the prefix (@ or /) with nothing after
   * - Status is "known" if token matches a known handle/command
   * - Status is "unknown" if token doesn't match any known handle/command
   */
  parse(
    text: string,
    knownHandles: string[],
    knownCommands: string[],
  ): TokenSegment[] {
    if (!text) return [];

    const segments: TokenSegment[] = [];
    const handleSet = new Set(knownHandles.map((h) => h.toLowerCase()));
    const commandSet = new Set(knownCommands.map((c) => c.toLowerCase()));

    const tokenRegex = /(@[a-z0-9-]*|\/[a-z0-9-]*)/gi;

    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = tokenRegex.exec(text)) !== null) {
      const matchStart = match.index;
      const matchEnd = matchStart + match[0].length;

      // Plain text before this match
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

      // Only highlight tokens at start of word
      const beforeMatch = text.slice(0, matchStart);
      const isStartOfWord = matchStart === 0 || /\s$/.test(beforeMatch);

      if (isStartOfWord && isHandle) {
        const handleName = tokenText.slice(1).toLowerCase();
        const status: TokenStatus =
          handleName.length === 0
            ? 'incomplete'
            : handleSet.has(handleName)
              ? 'known'
              : 'unknown';
        segments.push({ text: tokenText, type: 'handle', status });
      } else if (isStartOfWord && isCommand) {
        const commandName = tokenText.slice(1).toLowerCase();
        const status: TokenStatus =
          commandName.length === 0
            ? 'incomplete'
            : commandSet.has(commandName)
              ? 'known'
              : 'unknown';
        segments.push({ text: tokenText, type: 'command', status });
      } else {
        segments.push({ text: tokenText, type: 'plain', status: 'known' });
      }

      lastIndex = matchEnd;
    }

    // Remaining plain text
    if (lastIndex < text.length) {
      segments.push({
        text: text.slice(lastIndex),
        type: 'plain',
        status: 'known',
      });
    }

    return segments;
  }
}
