/**
 * ContactForm - Add/edit contact form with validation.
 *
 * Features:
 * - Handle auto-slug from display name
 * - Country dropdown with common codes
 * - Usage checkboxes (ship_to, shipper, third_party)
 * - Tag chips with add/remove
 */

import * as React from 'react';
import { X, Plus } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import type { Contact, ContactCreate, ContactUpdate } from '@/types/api';

// Simple Label component
function Label({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="text-sm font-medium text-foreground">
      {children}
    </label>
  );
}

// Common country codes
const COUNTRY_CODES = [
  { code: 'US', name: 'United States' },
  { code: 'CA', name: 'Canada' },
  { code: 'MX', name: 'Mexico' },
  { code: 'GB', name: 'United Kingdom' },
  { code: 'DE', name: 'Germany' },
  { code: 'FR', name: 'France' },
  { code: 'AU', name: 'Australia' },
  { code: 'JP', name: 'Japan' },
];

interface ContactFormProps {
  contact?: Contact | null;
  onSubmit: (data: ContactCreate | ContactUpdate) => Promise<void>;
  onCancel: () => void;
  isLoading?: boolean;
}

export function ContactForm({
  contact,
  onSubmit,
  onCancel,
  isLoading,
}: ContactFormProps) {
  const isEditing = !!contact;

  // Form state
  const [displayName, setDisplayName] = React.useState(contact?.display_name || '');
  const [handle, setHandle] = React.useState(contact?.handle || '');
  const [company, setCompany] = React.useState(contact?.company || '');
  const [attentionName, setAttentionName] = React.useState(contact?.attention_name || '');
  const [phone, setPhone] = React.useState(contact?.phone || '');
  const [email, setEmail] = React.useState(contact?.email || '');
  const [addressLine1, setAddressLine1] = React.useState(contact?.address_line_1 || '');
  const [addressLine2, setAddressLine2] = React.useState(contact?.address_line_2 || '');
  const [city, setCity] = React.useState(contact?.city || '');
  const [stateProvince, setStateProvince] = React.useState(contact?.state_province || '');
  const [postalCode, setPostalCode] = React.useState(contact?.postal_code || '');
  const [countryCode, setCountryCode] = React.useState(contact?.country_code || 'US');
  const [useAsShipTo, setUseAsShipTo] = React.useState(contact?.use_as_ship_to ?? true);
  const [useAsShipper, setUseAsShipper] = React.useState(contact?.use_as_shipper ?? false);
  const [useAsThirdParty, setUseAsThirdParty] = React.useState(contact?.use_as_third_party ?? false);
  const [tags, setTags] = React.useState<string[]>(contact?.tags || []);
  const [tagInput, setTagInput] = React.useState('');
  const [notes, setNotes] = React.useState(contact?.notes || '');

  // Auto-slug handle from display name
  const autoSlugHandle = React.useCallback((name: string) => {
    return name
      .toLowerCase()
      .replace(/'/g, '')
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 50);
  }, []);

  const handleDisplayNameChange = (value: string) => {
    setDisplayName(value);
    if (!isEditing && !handle) {
      setHandle(autoSlugHandle(value));
    }
  };

  const addTag = () => {
    const trimmed = tagInput.trim().toLowerCase();
    if (trimmed && !tags.includes(trimmed)) {
      setTags([...tags, trimmed]);
      setTagInput('');
    }
  };

  const removeTag = (tag: string) => {
    setTags(tags.filter((t) => t !== tag));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const data: ContactCreate | ContactUpdate = {
      display_name: displayName,
      handle: handle || undefined,
      company: company || undefined,
      attention_name: attentionName || undefined,
      phone: phone || undefined,
      email: email || undefined,
      address_line_1: addressLine1,
      address_line_2: addressLine2 || undefined,
      city,
      state_province: stateProvince,
      postal_code: postalCode,
      country_code: countryCode,
      use_as_ship_to: useAsShipTo,
      use_as_shipper: useAsShipper,
      use_as_third_party: useAsThirdParty,
      tags: tags.length > 0 ? tags : undefined,
      notes: notes || undefined,
    };

    await onSubmit(data);
  };

  const isValid = displayName && addressLine1 && city && stateProvince && postalCode;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Handle */}
      <div className="space-y-1.5">
        <Label htmlFor="handle">Handle</Label>
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">@</span>
          <Input
            id="handle"
            value={handle}
            onChange={(e) => setHandle(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
            placeholder="auto-generated if empty"
            className="font-mono"
          />
        </div>
      </div>

      {/* Display Name */}
      <div className="space-y-1.5">
        <Label htmlFor="displayName">Display Name *</Label>
        <Input
          id="displayName"
          value={displayName}
          onChange={(e) => handleDisplayNameChange(e.target.value)}
          placeholder="John Doe"
          required
        />
      </div>

      {/* Company + Attention */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="company">Company</Label>
          <Input
            id="company"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="Acme Inc"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="attention">Attention</Label>
          <Input
            id="attention"
            value={attentionName}
            onChange={(e) => setAttentionName(e.target.value)}
            placeholder="Shipping Dept"
          />
        </div>
      </div>

      {/* Phone + Email */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="phone">Phone</Label>
          <Input
            id="phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+14155550100"
            type="tel"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="john@example.com"
            type="email"
          />
        </div>
      </div>

      {/* Address */}
      <div className="space-y-1.5">
        <Label htmlFor="address1">Address Line 1 *</Label>
        <Input
          id="address1"
          value={addressLine1}
          onChange={(e) => setAddressLine1(e.target.value)}
          placeholder="123 Main St"
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="address2">Address Line 2</Label>
        <Input
          id="address2"
          value={addressLine2}
          onChange={(e) => setAddressLine2(e.target.value)}
          placeholder="Suite 100"
        />
      </div>

      {/* City, State, Postal, Country */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="city">City *</Label>
          <Input
            id="city"
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder="San Francisco"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="state">State/Province *</Label>
          <Input
            id="state"
            value={stateProvince}
            onChange={(e) => setStateProvince(e.target.value)}
            placeholder="CA"
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="postal">Postal Code *</Label>
          <Input
            id="postal"
            value={postalCode}
            onChange={(e) => setPostalCode(e.target.value)}
            placeholder="94105"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="country">Country</Label>
          <select
            id="country"
            value={countryCode}
            onChange={(e) => setCountryCode(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {COUNTRY_CODES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} — {c.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Usage checkboxes */}
      <div className="space-y-2">
        <Label>Usage</Label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={useAsShipTo}
              onChange={(e) => setUseAsShipTo(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <span className="text-sm">Ship To</span>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={useAsShipper}
              onChange={(e) => setUseAsShipper(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <span className="text-sm">Shipper</span>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={useAsThirdParty}
              onChange={(e) => setUseAsThirdParty(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <span className="text-sm">Third Party</span>
          </label>
        </div>
      </div>

      {/* Tags */}
      <div className="space-y-2">
        <Label>Tags</Label>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-muted rounded text-xs"
            >
              {tag}
              <button
                type="button"
                onClick={() => removeTag(tag)}
                className="hover:text-destructive"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addTag();
              }
            }}
            placeholder="Add tag"
            className="h-8 text-sm"
          />
          <Button type="button" variant="outline" size="sm" onClick={addTag}>
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Notes */}
      <div className="space-y-1.5">
        <Label htmlFor="notes">Notes</Label>
        <textarea
          id="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Additional notes..."
          rows={2}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!isValid || isLoading}>
          {isLoading ? 'Saving...' : isEditing ? 'Update Contact' : 'Create Contact'}
        </Button>
      </div>
    </form>
  );
}

export default ContactForm;
