/**
 * Token expansion for /command and @handle tokens.
 *
 * Scans input text for /commandName and @handleName patterns,
 * replaces each with its expanded content, and returns the
 * fully expanded string. Unknown tokens are left as-is.
 *
 * Uses the same regex patterns as useTokenHighlighter for consistency.
 */

import type { Contact, CustomCommand } from '@/types/api';

/** Token regex matching @handle and /command patterns (same as useTokenHighlighter). */
const TOKEN_REGEX = /(@[a-z0-9-]+|\/[a-z0-9-]+)/gi;

/**
 * Build a structured natural-language address block for the agent.
 * Omits null/empty fields.
 */
function formatContactBlock(contact: Contact): string {
  const parts: string[] = [contact.display_name];

  if (contact.company) parts.push(contact.company);
  parts.push(contact.address_line_1);
  if (contact.address_line_2) parts.push(contact.address_line_2);
  parts.push(`${contact.city}${contact.state_province ? `, ${contact.state_province}` : ''} ${contact.postal_code}`);
  parts.push(contact.country_code);
  if (contact.phone) parts.push(`phone: ${contact.phone}`);
  if (contact.email) parts.push(`email: ${contact.email}`);
  if (contact.attention_name) parts.push(`attn: ${contact.attention_name}`);

  return `[Contact: ${parts.join(', ')}]`;
}

/**
 * Expand /command and @handle tokens in the input text.
 *
 * - /commandName → command's body field verbatim
 * - @handleName  → structured address block for the agent
 * - Unknown tokens are left as-is
 *
 * @returns The fully expanded string.
 */
export function expandTokens(
  text: string,
  contacts: Contact[],
  commands: CustomCommand[]
): string {
  if (!text) return text;

  // Build lookup maps (case-insensitive)
  const contactMap = new Map<string, Contact>();
  for (const c of contacts) {
    contactMap.set(c.handle.toLowerCase(), c);
  }

  const commandMap = new Map<string, CustomCommand>();
  for (const cmd of commands) {
    commandMap.set(cmd.name.toLowerCase(), cmd);
  }

  return text.replace(TOKEN_REGEX, (match, _group, offset) => {
    // Only expand tokens that appear at start of word (after whitespace or start of string)
    if (offset > 0 && !/\s/.test(text[offset - 1])) {
      return match;
    }

    if (match.startsWith('/')) {
      const name = match.slice(1).toLowerCase();
      const cmd = commandMap.get(name);
      return cmd ? cmd.body : match;
    }

    if (match.startsWith('@')) {
      const handle = match.slice(1).toLowerCase();
      const contact = contactMap.get(handle);
      return contact ? formatContactBlock(contact) : match;
    }

    return match;
  });
}
