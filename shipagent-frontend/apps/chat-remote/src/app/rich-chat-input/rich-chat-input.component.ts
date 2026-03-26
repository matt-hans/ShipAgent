/**
 * RichChatInputComponent — Token-highlighted input with autocomplete.
 *
 * Features:
 * - Mirror div technique: hidden textarea + styled overlay
 * - @handle and /command token highlighting via TokenHighlighterService
 * - Autocomplete popovers for contacts and commands
 * - Token colours: teal (OKLCH 185) for @handles, amber (OKLCH 85) for /commands
 * - Submit on Enter (Shift+Enter for newline)
 *
 * Providers (all component-scoped):
 *   CommandAutocompleteService, ContactAutocompleteService,
 *   TokenHighlighterService, TokenExpansionService
 */

import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MirrorSyncDirective } from '@shipagent/shared-ui';
import { ContactsStore, CommandsStore } from '@shipagent/shared-state';
import { CommandAutocompleteService } from '../../services/command-autocomplete.service';
import { ContactAutocompleteService } from '../../services/contact-autocomplete.service';
import { TokenHighlighterService } from '../../services/token-highlighter.service';
import { TokenExpansionService } from '../../services/token-expansion.service';
import type { TokenSegment } from '../../services/token-highlighter.service';

@Component({
  selector: 'app-rich-chat-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [
    CommandAutocompleteService,
    ContactAutocompleteService,
    TokenHighlighterService,
    TokenExpansionService,
  ],
  imports: [CommonModule, MirrorSyncDirective],
  styles: [`
    .rich-input-wrapper {
      position: relative;
      width: 100%;
    }
    .rich-input-mirror {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      padding: 0.5rem 0.75rem;
      font-size: 0.875rem;
      line-height: 1.5;
      font-family: inherit;
      white-space: pre-wrap;
      overflow-y: auto;
      overflow-x: hidden;
      pointer-events: none;
      word-break: break-word;
      color: transparent;
    }
    .rich-input-textarea {
      position: relative;
      background: transparent;
      z-index: 1;
      width: 100%;
      min-height: 40px;
      max-height: 200px;
      padding: 0.5rem 0.75rem;
      font-size: 0.875rem;
      line-height: 1.5;
      font-family: inherit;
      color: inherit;
      border: 1px solid oklch(0.3 0.02 240);
      border-radius: 0.5rem;
      outline: none;
      resize: none;
      background-color: transparent;
      caret-color: oklch(0.7 0.15 200);
      overflow-y: auto;
    }
    .rich-input-textarea:focus {
      border-color: oklch(0.55 0.2 220);
    }
    .token-handle {
      background-color: oklch(0.65 0.15 185 / 0.2);
      color: oklch(0.75 0.15 185);
      border-radius: 2px;
    }
    .token-handle--unknown { color: oklch(0.7 0.08 185); }
    .token-handle--incomplete { color: oklch(0.6 0.05 185); }
    .token-command {
      background-color: oklch(0.8 0.15 85 / 0.2);
      color: oklch(0.8 0.15 85);
      border-radius: 2px;
    }
    .token-command--unknown { color: oklch(0.7 0.08 85); }
    .token-command--incomplete { color: oklch(0.65 0.05 85); }
    .autocomplete-popover {
      position: absolute;
      bottom: calc(100% + 4px);
      left: 0;
      right: 0;
      z-index: 50;
      background: oklch(0.15 0.01 240);
      border: 1px solid oklch(0.25 0.02 240);
      border-radius: 0.5rem;
      overflow: hidden;
      box-shadow: 0 8px 24px oklch(0 0 0 / 0.4);
    }
    .autocomplete-item {
      display: flex;
      align-items: center;
      width: 100%;
      padding: 0.5rem 0.75rem;
      text-align: left;
      cursor: pointer;
      transition: background-color 0.1s;
    }
    .autocomplete-item:hover,
    .autocomplete-item--selected {
      background-color: oklch(0.22 0.02 240);
    }
  `],
  template: `
    <div class="rich-input-wrapper">
      <!-- Mirror div for token highlighting -->
      <div #mirrorDiv class="rich-input-mirror" aria-hidden="true">
        @for (seg of segments(); track $index) {
          @if (seg.type === 'plain') {
            <span>{{ seg.text }}</span>
          } @else if (seg.type === 'handle') {
            <span [class]="handleClass(seg)">{{ seg.text }}</span>
          } @else if (seg.type === 'command') {
            <span [class]="commandClass(seg)">{{ seg.text }}</span>
          }
        }
        <!-- Trailing space to match textarea behavior -->
        <span>&nbsp;</span>
      </div>

      <!-- Actual textarea -->
      <textarea
        #inputTextarea
        class="rich-input-textarea"
        appMirrorSync
        [mirrorTarget]="mirrorDiv"
        [value]="value"
        [placeholder]="placeholder"
        [disabled]="disabled"
        (input)="handleInput($event)"
        (keydown)="handleKeyDown($event)"
        (select)="handleCursorChange($event)"
        (click)="handleCursorChange($event)"
        rows="1"
      ></textarea>

      <!-- Contact autocomplete popover -->
      @if (contactAuto.isOpen() && contactAuto.filteredContacts().length > 0) {
        <div class="autocomplete-popover">
          @for (candidate of contactAuto.filteredContacts(); track candidate.handle; let i = $index) {
            <button
              type="button"
              class="autocomplete-item"
              [class.autocomplete-item--selected]="i === contactAuto.selectedIndex()"
              (click)="selectContact(candidate)"
              (mouseenter)="contactAuto.selectedIndex.set(i)"
            >
              <span class="font-mono text-xs" style="color: oklch(0.75 0.15 185);">&#64;{{ candidate.handle }}</span>
              <span class="text-xs text-slate-400 ml-2">
                {{ candidate.display_name }} — {{ candidate.city }}{{ candidate.state_province ? ', ' + candidate.state_province : '' }}
              </span>
            </button>
          }
        </div>
      }

      <!-- Command autocomplete popover -->
      @if (commandAuto.isOpen() && commandAuto.filteredCommands().length > 0) {
        <div class="autocomplete-popover">
          @for (candidate of commandAuto.filteredCommands(); track candidate.name; let i = $index) {
            <button
              type="button"
              class="autocomplete-item"
              [class.autocomplete-item--selected]="i === commandAuto.selectedIndex()"
              (click)="selectCommand(candidate)"
              (mouseenter)="commandAuto.selectedIndex.set(i)"
            >
              <span class="font-mono text-xs" style="color: oklch(0.8 0.15 85);">/{{ candidate.name }}</span>
              <span class="text-xs text-slate-400 ml-2">
                {{ candidate.description || candidate.body.slice(0, 40) }}
              </span>
            </button>
          }
        </div>
      }
    </div>
  `,
})
export class RichChatInputComponent implements OnChanges {
  @ViewChild('inputTextarea') private textareaEl?: ElementRef<HTMLTextAreaElement>;

  @Input() value = '';
  @Input() placeholder = 'Enter a command...';
  @Input() disabled = false;

  @Output() valueChange = new EventEmitter<string>();
  @Output() messageSent = new EventEmitter<string>();

  readonly commandAuto = inject(CommandAutocompleteService);
  readonly contactAuto = inject(ContactAutocompleteService);
  private readonly tokenHighlighter = inject(TokenHighlighterService);
  private readonly tokenExpansion = inject(TokenExpansionService);
  private readonly contactsStore = inject(ContactsStore);
  private readonly commandsStore = inject(CommandsStore);

  private readonly cursorPosition = signal(0);

  /** Token segments for mirror div rendering — recomputed on value or store changes. */
  readonly segments = computed<TokenSegment[]>(() => {
    const knownHandles = this.contactsStore.contacts().map((c) => c.handle);
    const knownCommands = this.commandsStore.customCommands().map((c) => c.name);
    return this.tokenHighlighter.parse(this.value, knownHandles, knownCommands);
  });

  ngOnChanges(_changes: SimpleChanges): void {
    // Update autocomplete when value changes externally
    this.updateAutocomplete();
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  handleInput(event: Event): void {
    const target = event.target as HTMLTextAreaElement;
    const newValue = target.value;
    const cursor = target.selectionStart ?? 0;
    this.cursorPosition.set(cursor);
    this.valueChange.emit(newValue);
    // Sync to parent's @Input so segments recompute
    this.value = newValue;
    this.updateAutocomplete();
  }

  handleCursorChange(event: Event): void {
    const target = event.target as HTMLTextAreaElement;
    this.cursorPosition.set(target.selectionStart ?? 0);
    this.updateAutocomplete();
  }

  handleKeyDown(event: KeyboardEvent): void {
    // Contact autocomplete navigation
    if (this.contactAuto.isOpen()) {
      if (event.key === 'ArrowDown') { event.preventDefault(); this.contactAuto.moveSelection(1); return; }
      if (event.key === 'ArrowUp')   { event.preventDefault(); this.contactAuto.moveSelection(-1); return; }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        const c = this.contactAuto.getSelected();
        if (c) this.selectContact(c);
        return;
      }
      if (event.key === 'Escape') { this.contactAuto.close(); return; }
    }

    // Command autocomplete navigation
    if (this.commandAuto.isOpen()) {
      if (event.key === 'ArrowDown') { event.preventDefault(); this.commandAuto.moveSelection(1); return; }
      if (event.key === 'ArrowUp')   { event.preventDefault(); this.commandAuto.moveSelection(-1); return; }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        const c = this.commandAuto.getSelected();
        if (c) this.selectCommand(c);
        return;
      }
      if (event.key === 'Escape') { this.commandAuto.close(); return; }
    }

    // Submit on Enter (no popover open, no Shift)
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submit();
    }
  }

  // ---------------------------------------------------------------------------
  // Autocomplete selection
  // ---------------------------------------------------------------------------

  selectContact(candidate: { handle: string; display_name: string; city: string; state_province: string | null }): void {
    const newText = this.contactAuto.select(this.value, candidate);
    this.value = newText;
    this.valueChange.emit(newText);
    this.contactAuto.close();
    this.commandAuto.close();
    // Restore focus
    setTimeout(() => this.focusAtEnd(this.contactAuto.tokenStart() + candidate.handle.length + 2), 0);
  }

  selectCommand(candidate: { name: string; description: string | null; body: string }): void {
    const newText = this.commandAuto.select(this.value, candidate);
    this.value = newText;
    this.valueChange.emit(newText);
    this.commandAuto.close();
    this.contactAuto.close();
    setTimeout(() => this.focusAtEnd(this.commandAuto.tokenStart() + candidate.name.length + 2), 0);
  }

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  private submit(): void {
    const text = this.value.trim();
    if (!text || this.disabled) return;
    const expanded = this.tokenExpansion.expand(
      text,
      this.contactsStore.contacts(),
      this.commandsStore.customCommands(),
    );
    this.messageSent.emit(expanded);
  }

  private updateAutocomplete(): void {
    const cursor = this.cursorPosition();
    // Run contact first; if active, close command (only one popover at a time)
    const contactActive = this.contactAuto.filter(this.value, cursor);
    const commandActive = !contactActive && this.commandAuto.filter(this.value, cursor);
    if (contactActive) this.commandAuto.close();
    if (commandActive) this.contactAuto.close();
    if (!contactActive && !commandActive) {
      this.contactAuto.close();
      this.commandAuto.close();
    }
  }

  private focusAtEnd(position: number): void {
    const el = this.textareaEl?.nativeElement;
    if (!el) return;
    el.focus();
    el.setSelectionRange(position, position);
  }

  // CSS class helpers for mirror div segments
  handleClass(seg: TokenSegment): string {
    const classes = ['token-handle'];
    if (seg.status === 'unknown') classes.push('token-handle--unknown');
    if (seg.status === 'incomplete') classes.push('token-handle--incomplete');
    return classes.join(' ');
  }

  commandClass(seg: TokenSegment): string {
    const classes = ['token-command'];
    if (seg.status === 'unknown') classes.push('token-command--unknown');
    if (seg.status === 'incomplete') classes.push('token-command--incomplete');
    return classes.join(' ');
  }
}
