/**
 * TokenExpansionService — Port of expandTokens.ts.
 *
 * Expands /command and @handle tokens in input text before sending to the API.
 * - /commandName → command's body field verbatim
 * - @handleName  → structured address block for the agent
 * - Unknown tokens are left as-is
 *
 * Provided at component level.
 */

import { Injectable } from '@angular/core';
import type { Contact, CustomCommand } from '@shipagent/shared-types';

/** Token regex matching @handle and /command patterns. */
const TOKEN_REGEX = /(@[a-z0-9-]+|\/[a-z0-9-]+)/gi;

@Injectable()
export class TokenExpansionService {
  /**
   * Expand /command and @handle tokens in the input text.
   * Unknown tokens are left unchanged.
   */
  expand(text: string, contacts: Contact[], commands: CustomCommand[]): string {
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

    return text.replace(TOKEN_REGEX, (match: string, _group: string, offset: number) => {
      // Only expand tokens at start of word
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
        return contact ? this.formatContactBlock(contact) : match;
      }

      return match;
    });
  }

  /** Format a contact as a structured natural-language address block. */
  private formatContactBlock(contact: Contact): string {
    const parts: string[] = [contact.display_name];

    if (contact.company) parts.push(contact.company);
    parts.push(contact.address_line_1);
    if (contact.address_line_2) parts.push(contact.address_line_2);
    parts.push(
      `${contact.city}${contact.state_province ? `, ${contact.state_province}` : ''} ${contact.postal_code}`,
    );
    parts.push(contact.country_code);
    if (contact.phone) parts.push(`phone: ${contact.phone}`);
    if (contact.email) parts.push(`email: ${contact.email}`);
    if (contact.attention_name) parts.push(`attn: ${contact.attention_name}`);

    return `[Contact: ${parts.join(', ')}]`;
  }
}
