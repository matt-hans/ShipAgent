/**
 * RichChatInput - Token-highlighted input with autocomplete.
 *
 * Features:
 * - Mirror div technique: hidden textarea + styled overlay
 * - @handle and /command token highlighting
 * - Autocomplete popovers for contacts and commands
 * - Token colours: teal (OKLCH 185) for @handles, amber (OKLCH 85) for /commands
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import { useAppState } from '@/hooks/useAppState';
import { useTokenHighlighter } from '@/hooks/useTokenHighlighter';
import { useContactAutocomplete, insertContactHandle } from '@/hooks/useContactAutocomplete';
import { useCommandAutocomplete, insertCommandName } from '@/hooks/useCommandAutocomplete';
import type { ContactCandidate } from '@/hooks/useContactAutocomplete';
import type { CommandCandidate } from '@/hooks/useCommandAutocomplete';

interface RichChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export function RichChatInput({
  value,
  onChange,
  onSubmit,
  placeholder = 'Enter a command...',
  disabled = false,
  className,
}: RichChatInputProps) {
  const { contacts, customCommands } = useAppState();

  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const mirrorRef = React.useRef<HTMLDivElement>(null);
  const [cursorPosition, setCursorPosition] = React.useState(0);
  const [showContactPopover, setShowContactPopover] = React.useState(false);
  const [showCommandPopover, setShowCommandPopover] = React.useState(false);
  const [selectedContactIndex, setSelectedContactIndex] = React.useState(0);
  const [selectedCommandIndex, setSelectedCommandIndex] = React.useState(0);

  // Token highlighting
  const segments = useTokenHighlighter({
    text: value,
    knownHandles: contacts.map((c) => c.handle),
    knownCommands: customCommands.map((c) => c.name),
  });

  // Autocomplete hooks
  const contactAuto = useContactAutocomplete({
    text: value,
    cursorPosition,
    contacts,
  });

  const commandAuto = useCommandAutocomplete({
    text: value,
    cursorPosition,
    commands: customCommands,
  });

  // Sync scroll between textarea and mirror
  const handleScroll = React.useCallback(() => {
    if (textareaRef.current && mirrorRef.current) {
      mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
      mirrorRef.current.scrollLeft = textareaRef.current.scrollLeft;
    }
  }, []);

  // Handle input change
  const handleChange = React.useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
      setCursorPosition(e.target.selectionStart);
    },
    [onChange]
  );

  // Handle cursor position changes
  const handleSelect = React.useCallback(
    (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
      const target = e.target as HTMLTextAreaElement;
      setCursorPosition(target.selectionStart);
    },
    []
  );

  // Show/hide popovers based on autocomplete state
  React.useEffect(() => {
    setShowContactPopover(contactAuto.isActive && contactAuto.candidates.length > 0);
    setShowCommandPopover(commandAuto.isActive && commandAuto.candidates.length > 0);
    setSelectedContactIndex(0);
    setSelectedCommandIndex(0);
  }, [contactAuto.isActive, contactAuto.candidates.length, commandAuto.isActive, commandAuto.candidates.length]);

  // Handle contact selection
  const selectContact = React.useCallback(
    (candidate: ContactCandidate) => {
      const newText = insertContactHandle(
        value,
        candidate.handle,
        contactAuto.tokenStart,
        contactAuto.tokenEnd
      );
      onChange(newText);
      setShowContactPopover(false);
      // Focus back to textarea
      setTimeout(() => {
        if (textareaRef.current) {
          const newPos = contactAuto.tokenStart + candidate.handle.length + 2;
          textareaRef.current.focus();
          textareaRef.current.setSelectionRange(newPos, newPos);
        }
      }, 0);
    },
    [value, contactAuto, onChange]
  );

  // Handle command selection
  const selectCommand = React.useCallback(
    (candidate: CommandCandidate) => {
      const newText = insertCommandName(
        value,
        candidate.name,
        commandAuto.tokenStart,
        commandAuto.tokenEnd
      );
      onChange(newText);
      setShowCommandPopover(false);
      setTimeout(() => {
        if (textareaRef.current) {
          const newPos = commandAuto.tokenStart + candidate.name.length + 2;
          textareaRef.current.focus();
          textareaRef.current.setSelectionRange(newPos, newPos);
        }
      }, 0);
    },
    [value, commandAuto, onChange]
  );

  // Handle keyboard navigation
  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Contact autocomplete navigation
      if (showContactPopover) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedContactIndex((i) =>
            Math.min(i + 1, contactAuto.candidates.length - 1)
          );
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedContactIndex((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          const candidate = contactAuto.candidates[selectedContactIndex];
          if (candidate) {
            selectContact(candidate);
          }
          return;
        }
        if (e.key === 'Escape') {
          setShowContactPopover(false);
          return;
        }
      }

      // Command autocomplete navigation
      if (showCommandPopover) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedCommandIndex((i) =>
            Math.min(i + 1, commandAuto.candidates.length - 1)
          );
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedCommandIndex((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          const candidate = commandAuto.candidates[selectedCommandIndex];
          if (candidate) {
            selectCommand(candidate);
          }
          return;
        }
        if (e.key === 'Escape') {
          setShowCommandPopover(false);
          return;
        }
      }

      // Submit on Enter (when no popover is open)
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        onSubmit();
      }
    },
    [
      showContactPopover,
      showCommandPopover,
      contactAuto.candidates,
      commandAuto.candidates,
      selectedContactIndex,
      selectedCommandIndex,
      selectContact,
      selectCommand,
      onSubmit,
    ]
  );

  // Render token with appropriate styling
  const renderToken = (segment: { text: string; type: string; status: string }, index: number) => {
    if (segment.type === 'plain') {
      return <span key={index}>{segment.text}</span>;
    }

    if (segment.type === 'handle') {
      return (
        <span
          key={index}
          className={cn(
            'token-handle',
            segment.status === 'unknown' && 'token-handle--unknown',
            segment.status === 'incomplete' && 'token-handle--incomplete'
          )}
        >
          {segment.text}
        </span>
      );
    }

    if (segment.type === 'command') {
      return (
        <span
          key={index}
          className={cn(
            'token-command',
            segment.status === 'unknown' && 'token-command--unknown',
            segment.status === 'incomplete' && 'token-command--incomplete'
          )}
        >
          {segment.text}
        </span>
      );
    }

    return <span key={index}>{segment.text}</span>;
  };

  return (
    <div className={cn('relative', className)}>
      {/* Mirror div for highlighting */}
      <div
        ref={mirrorRef}
        className="rich-input-mirror"
        aria-hidden="true"
      >
        {segments.map(renderToken)}
        {/* Trailing space to match textarea behavior */}
        <span>&nbsp;</span>
      </div>

      {/* Actual textarea */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onSelect={handleSelect}
        onScroll={handleScroll}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        className="rich-input-textarea"
        rows={1}
      />

      {/* Contact autocomplete popover */}
      {showContactPopover && (
        <div className="autocomplete-popover">
          {contactAuto.candidates.map((candidate, index) => (
            <button
              key={candidate.handle}
              className={cn(
                'autocomplete-item',
                index === selectedContactIndex && 'autocomplete-item--selected'
              )}
              onClick={() => selectContact(candidate)}
              onMouseEnter={() => setSelectedContactIndex(index)}
            >
              <span className="font-mono text-domain-locator">@{candidate.handle}</span>
              <span className="text-muted-foreground ml-2 text-xs">
                {candidate.display_name} — {candidate.city}, {candidate.state_province}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Command autocomplete popover */}
      {showCommandPopover && (
        <div className="autocomplete-popover">
          {commandAuto.candidates.map((candidate, index) => (
            <button
              key={candidate.name}
              className={cn(
                'autocomplete-item',
                index === selectedCommandIndex && 'autocomplete-item--selected'
              )}
              onClick={() => selectCommand(candidate)}
              onMouseEnter={() => setSelectedCommandIndex(index)}
            >
              <span className="font-mono text-domain-paperless">/{candidate.name}</span>
              <span className="text-muted-foreground ml-2 text-xs">
                {candidate.description || candidate.body.slice(0, 40)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default RichChatInput;
