/**
 * CommandAutocompleteService — Port of useCommandAutocomplete.ts.
 *
 * Detects /command tokens at the cursor position and returns filtered
 * candidates from the CommandsStore. Provides insertion helpers.
 *
 * Provided at component level (tied to RichChatInputComponent lifecycle).
 */

import { Injectable, inject, signal } from '@angular/core';
import { CommandsStore } from '@shipagent/shared-state';
import type { CustomCommand } from '@shipagent/shared-types';

export interface CommandCandidate {
  name: string;
  description: string | null;
  body: string;
}

@Injectable()
export class CommandAutocompleteService {
  private readonly commandsStore = inject(CommandsStore);

  // ---------------------------------------------------------------------------
  // State signals
  // ---------------------------------------------------------------------------

  readonly isOpen = signal(false);
  readonly selectedIndex = signal(0);
  readonly filteredCommands = signal<CommandCandidate[]>([]);
  readonly tokenStart = signal(0);
  readonly tokenEnd = signal(0);
  readonly query = signal('');

  // ---------------------------------------------------------------------------
  // Filter based on text + cursor position
  // ---------------------------------------------------------------------------

  /**
   * Update the autocomplete state based on the current text and cursor position.
   * Returns true if autocomplete is active.
   */
  filter(text: string, cursorPosition: number): boolean {
    const textBeforeCursor = text.slice(0, cursorPosition);
    const lastSlashIndex = textBeforeCursor.lastIndexOf('/');

    if (lastSlashIndex === -1) {
      this.close();
      return false;
    }

    const textAfterSlash = textBeforeCursor.slice(lastSlashIndex + 1);
    // Invalidate if space between / and cursor
    if (textAfterSlash.includes(' ')) {
      this.close();
      return false;
    }

    // Only trigger at start of word
    const charBeforeSlash = lastSlashIndex > 0 ? text[lastSlashIndex - 1] : ' ';
    if (charBeforeSlash !== ' ' && charBeforeSlash !== '\n' && lastSlashIndex !== 0) {
      this.close();
      return false;
    }

    const q = textAfterSlash.toLowerCase();
    const commands = this.commandsStore.customCommands();
    const candidates: CommandCandidate[] = commands
      .filter((c: CustomCommand) => c.name.toLowerCase().startsWith(q))
      .slice(0, 8)
      .map((c: CustomCommand) => ({ name: c.name, description: c.description, body: c.body }));

    if (candidates.length === 0) {
      this.close();
      return false;
    }

    this.query.set(q);
    this.tokenStart.set(lastSlashIndex);
    this.tokenEnd.set(cursorPosition);
    this.filteredCommands.set(candidates);
    this.isOpen.set(true);
    this.selectedIndex.set(0);
    return true;
  }

  /** Select a candidate and return the new text with the token replaced. */
  select(text: string, candidate: CommandCandidate): string {
    const start = this.tokenStart();
    const end = this.tokenEnd();
    const before = text.slice(0, start);
    const after = text.slice(end);
    return `${before}/${candidate.name} ${after}`;
  }

  /** Move selection up or down. */
  moveSelection(direction: 1 | -1): void {
    const max = this.filteredCommands().length - 1;
    this.selectedIndex.update((i) => Math.max(0, Math.min(max, i + direction)));
  }

  /** Get the currently selected candidate. */
  getSelected(): CommandCandidate | null {
    return this.filteredCommands()[this.selectedIndex()] ?? null;
  }

  /** Close the autocomplete popover. */
  close(): void {
    this.isOpen.set(false);
    this.filteredCommands.set([]);
    this.selectedIndex.set(0);
  }
}
