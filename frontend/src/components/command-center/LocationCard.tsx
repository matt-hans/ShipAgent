/**
 * Inline card for UPS location search results in the chat thread.
 *
 * Renders numbered location/facility entries with expand/collapse detail
 * panels and full flattened UPS response fields for each item.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { LocationResult } from '@/types/api';
import { MapPinIcon, ChevronDownIcon, PhoneIcon, HistoryIcon } from '@/components/ui/icons';

type LocationItem = NonNullable<LocationResult['locations']>[number];
type FacilityItem = NonNullable<LocationResult['facilities']>[number];

type DisplayItem = {
  id: string;
  title: string;
  subtitle: string;
  address?: Record<string, string> | string;
  phone?: string;
  hours?: Record<string, string>;
  details?: Record<string, unknown>;
};

/** Extract multi-line address parts from the UPS address record. */
function formatAddressLines(addr: Record<string, string>): string[] {
  return [
    addr.ConsigneeName || '',
    addr.AddressLine || addr.line || addr.address_line || '',
    [addr.City || addr.city, addr.StateProvinceCode || addr.state]
      .filter(Boolean)
      .join(', ') +
      (addr.PostalCode || addr.postal_code
        ? ' ' + (addr.PostalCode || addr.postal_code)
        : ''),
    (addr.CountryCode || addr.country_code || '') !== 'US'
      ? addr.CountryCode || addr.country_code || ''
      : '',
  ].filter(Boolean);
}

/** Compact single-line address for collapsed rows. */
function formatAddressCompact(addr: Record<string, string>): string {
  return [
    addr.ConsigneeName,
    addr.AddressLine || addr.line || addr.address_line,
    [addr.City || addr.city, addr.StateProvinceCode || addr.state]
      .filter(Boolean)
      .join(', '),
    addr.PostalCode || addr.postal_code,
  ]
    .filter(Boolean)
    .join(' · ');
}

function stringifyDetailValue(value: unknown): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function flattenDetails(
  value: unknown,
  prefix: string,
  rows: Array<[string, string]>
): void {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      rows.push([prefix, '[]']);
      return;
    }
    value.forEach((item, index) => {
      flattenDetails(item, `${prefix}[${index}]`, rows);
    });
    return;
  }

  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const entries = Object.entries(record);
    if (entries.length === 0) {
      rows.push([prefix, '{}']);
      return;
    }
    entries.forEach(([key, item]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      flattenDetails(item, path, rows);
    });
    return;
  }

  rows.push([prefix, stringifyDetailValue(value)]);
}

function collectDetails(details?: Record<string, unknown>): Array<[string, string]> {
  if (!details) return [];
  const rows: Array<[string, string]> = [];
  flattenDetails(details, '', rows);
  return rows.filter(([key]) => key.trim().length > 0);
}

export function LocationCard({ data }: { data: LocationResult }) {
  const [expandedItems, setExpandedItems] = React.useState<Set<number>>(new Set());

  const isServiceCenters = data.action === 'service_centers';
  const title = isServiceCenters ? 'UPS Service Centers' : 'UPS Locations';
  const items: DisplayItem[] = React.useMemo(() => {
    if (isServiceCenters) {
      return (data.facilities ?? []).map((fac: FacilityItem, index) => ({
        id: `facility-${index}-${fac.name || 'unknown'}`,
        title: fac.name || `Service Center ${index + 1}`,
        subtitle: fac.address || 'No address provided',
        address: fac.address,
        phone: fac.phone || fac.phones?.[0] || '',
        hours: fac.hours,
        details: fac.details,
      }));
    }

    return (data.locations ?? []).map((loc: LocationItem, index) => ({
      id: `location-${index}-${loc.id || 'unknown'}`,
      title: loc.address?.ConsigneeName || `Location ${index + 1}`,
      subtitle: formatAddressCompact(loc.address) || `Location ID ${loc.id || 'N/A'}`,
      address: loc.address,
      phone: loc.phone || loc.phones?.[0] || '',
      hours: loc.hours,
      details: loc.details,
    }));
  }, [data.facilities, data.locations, isServiceCenters]);
  const count = items.length;

  /** Toggle individual detail panel. */
  function toggleItem(index: number) {
    setExpandedItems((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-locator')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapPinIcon className="w-4 h-4 text-[var(--color-domain-locator)]" />
          <h4 className="text-sm font-medium text-foreground">{title}</h4>
        </div>
        <span className="badge badge-neutral">{count} found</span>
      </div>

      {/* Empty state */}
      {count === 0 && (
        <p className="text-xs text-muted-foreground">No locations found for the given criteria.</p>
      )}

      {/* Locations / facilities list */}
      {items.length > 0 && (
        <div className="rounded-md border border-border/50 overflow-hidden">
          {items.map((item, i) => {
            const isExpanded = expandedItems.has(i);
            const detailsRows = isExpanded ? collectDetails(item.details) : [];
            return (
              <div key={item.id} className="border-b border-border/30 last:border-0">
                {/* Collapsed row */}
                <button
                  onClick={() => toggleItem(i)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50 transition-colors cursor-pointer"
                >
                  {/* Number badge */}
                  <span className="w-6 h-6 rounded-full bg-[var(--color-domain-locator)]/15 text-[var(--color-domain-locator)] text-[10px] font-mono font-bold flex items-center justify-center flex-shrink-0">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-foreground truncate">{item.title}</p>
                    <p className="text-[11px] font-mono text-muted-foreground truncate">{item.subtitle}</p>
                  </div>
                  {/* Phone (collapsed) */}
                  {item.phone && (
                    <span className="text-[10px] font-mono text-muted-foreground hidden sm:block flex-shrink-0">
                      {item.phone}
                    </span>
                  )}
                  {/* Chevron */}
                  <ChevronDownIcon className={cn(
                    'w-3.5 h-3.5 text-muted-foreground transition-transform duration-200 flex-shrink-0',
                    isExpanded && 'rotate-180'
                  )} />
                </button>

                {/* Expanded detail panel */}
                {isExpanded && (
                  <div className="animate-fade-in px-3 pb-3 pt-1 border-t border-border/30 ml-9">
                    {/* Full address */}
                    {item.address && (
                      <div className="space-y-0.5 mb-2">
                        {typeof item.address === 'string' ? (
                          <p className="text-xs text-foreground">{item.address}</p>
                        ) : (
                          formatAddressLines(item.address).map((line, li) => (
                            <p key={li} className="text-xs text-foreground">{line}</p>
                          ))
                        )}
                      </div>
                    )}

                    {/* Phone link */}
                    {item.phone && (
                      <div className="flex items-center gap-1.5 mb-2">
                        <PhoneIcon className="w-3 h-3 text-muted-foreground" />
                        <a
                          href={`tel:${item.phone}`}
                          className="text-[10px] font-mono text-[var(--color-domain-locator)] hover:underline"
                        >
                          {item.phone}
                        </a>
                      </div>
                    )}

                    {/* Operating hours */}
                    {item.hours && Object.keys(item.hours).length > 0 && (
                      <div className="mt-2">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <HistoryIcon className="w-3 h-3 text-muted-foreground" />
                          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                            Hours
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                          {Object.entries(item.hours).map(([day, hours]) => (
                            <React.Fragment key={day}>
                              <span className="text-[10px] font-mono text-muted-foreground">{day}</span>
                              <span className="text-[10px] font-mono text-foreground">{hours}</span>
                            </React.Fragment>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Full detail payload */}
                    {detailsRows.length > 0 && (
                      <div className="mt-2">
                        <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
                          Full UPS Details
                        </div>
                        <div className="max-h-56 overflow-y-auto rounded border border-border/40 bg-background/40 p-2 space-y-1 scrollable">
                          {detailsRows.map(([key, value]) => (
                            <div key={`${item.id}-${key}`} className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2">
                              <span className="text-[10px] font-mono text-muted-foreground break-all">{key}</span>
                              <span className="text-[10px] font-mono text-foreground break-all">{value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
