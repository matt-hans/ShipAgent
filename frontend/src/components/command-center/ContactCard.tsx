/**
 * Inline card for contact saved results in the chat thread.
 *
 * Renders contact details with address, handle display, and action buttons
 * (Confirm, Edit, Delete). Uses rose domain color.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { ContactSavedResult } from '@/types/api';
import { useAppState } from '@/hooks/useAppState';
import * as api from '@/lib/api';
import { UserIcon, CheckIcon, EditIcon, TrashIcon } from '@/components/ui/icons';

interface ContactCardProps {
  data: ContactSavedResult;
  onEdit?: (handle: string) => void;
}

type CardState = 'active' | 'confirmed' | 'deleted';

export function ContactCard({ data, onEdit }: ContactCardProps) {
  const { refreshContacts } = useAppState();
  const [cardState, setCardState] = React.useState<CardState>('active');
  const [isDeleting, setIsDeleting] = React.useState(false);
  const [deleteConfirm, setDeleteConfirm] = React.useState(false);

  const handleConfirm = async () => {
    await refreshContacts();
    setCardState('confirmed');
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      // Find contact by handle to get the ID
      const response = await api.listContacts();
      const contact = response.contacts.find((c) => c.handle === data.handle);
      if (contact) {
        await api.deleteContact(contact.id);
        await refreshContacts();
      }
      setCardState('deleted');
    } catch (error) {
      console.error('Failed to delete contact:', error);
    } finally {
      setIsDeleting(false);
      setDeleteConfirm(false);
    }
  };

  // Confirmed state - minimal collapsed card
  if (cardState === 'confirmed') {
    return (
      <div className="card-premium p-3 border-l-4 card-domain-contacts">
        <div className="flex items-center gap-2 text-xs">
          <CheckIcon className="w-3.5 h-3.5 text-success" />
          <span className="text-muted-foreground">
            Contact <code className="font-mono text-[var(--color-domain-contacts)]">@{data.handle}</code> saved
          </span>
        </div>
      </div>
    );
  }

  // Deleted state
  if (cardState === 'deleted') {
    return (
      <div className="card-premium p-3 border-l-4 border-border">
        <div className="flex items-center gap-2 text-xs">
          <TrashIcon className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">
            Contact <code className="font-mono">@{data.handle}</code> removed
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-contacts')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <UserIcon className="w-4 h-4 text-[var(--color-domain-contacts)]" />
          <h4 className="text-sm font-medium text-foreground">Contact Saved</h4>
        </div>
        <span className={cn(
          'badge',
          data.action === 'created' ? 'badge-success' : 'badge-info'
        )}>
          {data.action === 'created' ? 'CREATED' : 'UPDATED'}
        </span>
      </div>

      {/* Contact details */}
      <div className="space-y-2">
        {/* Name and handle */}
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{data.display_name}</span>
          <code className="text-xs font-mono text-[var(--color-domain-contacts)]">@{data.handle}</code>
        </div>

        {/* Company / Attention */}
        {(data.company || data.attention_name) && (
          <div className="text-xs text-muted-foreground">
            {data.company && <span>{data.company}</span>}
            {data.company && data.attention_name && <span> · </span>}
            {data.attention_name && <span>Attn: {data.attention_name}</span>}
          </div>
        )}

        {/* Address */}
        <div className="text-xs text-muted-foreground leading-relaxed">
          <p>{data.address_line_1}</p>
          {data.address_line_2 && <p>{data.address_line_2}</p>}
          <p>
            {data.city}{data.state_province ? `, ${data.state_province}` : ''} {data.postal_code}
            {data.country_code !== 'US' && ` ${data.country_code}`}
          </p>
        </div>

        {/* Phone / Email */}
        {(data.phone || data.email) && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {data.phone && <span>{data.phone}</span>}
            {data.email && <span>{data.email}</span>}
          </div>
        )}

        {/* Tags */}
        {data.tags && data.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {data.tags.map((tag) => (
              <span
                key={tag}
                className="text-[10px] px-2 py-0.5 bg-muted rounded font-medium"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-border">
        <button
          onClick={handleConfirm}
          className="btn-primary px-3 py-1.5 text-xs gap-1.5"
        >
          <CheckIcon className="w-3.5 h-3.5" />
          Confirm
        </button>

        {onEdit && (
          <button
            onClick={() => onEdit(data.handle)}
            className="btn-secondary px-3 py-1.5 text-xs gap-1.5"
          >
            <EditIcon className="w-3.5 h-3.5" />
            Edit
          </button>
        )}

        {deleteConfirm ? (
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-[10px] text-muted-foreground">Delete?</span>
            <button
              onClick={handleDelete}
              disabled={isDeleting}
              className="px-2 py-1 text-[10px] rounded bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeleting ? 'Deleting...' : 'Yes'}
            </button>
            <button
              onClick={() => setDeleteConfirm(false)}
              className="px-2 py-1 text-[10px] rounded bg-muted hover:bg-muted/80"
            >
              No
            </button>
          </div>
        ) : (
          <button
            onClick={() => setDeleteConfirm(true)}
            className="btn-secondary px-3 py-1.5 text-xs gap-1.5 ml-auto"
          >
            <TrashIcon className="w-3.5 h-3.5" />
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
