/**
 * Inline card for UPS location search results in the chat thread.
 *
 * Renders numbered location entries with expand/collapse detail panels
 * (hours, full address, phone) and a show-more toggle. Service center
 * facilities render as a simpler numbered list. Uses teal domain color.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { LocationResult } from '@/types/api';
import { MapPinIcon, ChevronDownIcon, PhoneIcon, HistoryIcon } from '@/components/ui/icons';

const COLLAPSED_COUNT = 5;

/** Extract multi-line address parts from the UPS address record. */
function formatAddressLines(addr: Record<string, string>): string[] {
  return [
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
    addr.AddressLine || addr.line || addr.address_line,
    [addr.City || addr.city, addr.StateProvinceCode || addr.state]
      .filter(Boolean)
      .join(', '),
    addr.PostalCode || addr.postal_code,
  ]
    .filter(Boolean)
    .join(' · ');
}

export function LocationCard({ data }: { data: LocationResult }) {
  const [expandedLocations, setExpandedLocations] = React.useState<Set<number>>(new Set());
  const [isListExpanded, setIsListExpanded] = React.useState(false);

  const isServiceCenters = data.action === 'service_centers';
  const title = isServiceCenters ? 'UPS Service Centers' : 'UPS Locations';
  const items = isServiceCenters ? data.facilities : data.locations;
  const count = items?.length ?? 0;

  /** Toggle individual location detail panel. */
  function toggleLocation(index: number) {
    setExpandedLocations((prev) => {
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

      {/* Locations list */}
      {data.locations && data.locations.length > 0 && (
        <div className={cn(
          'rounded-md border border-border/50 overflow-hidden',
          isListExpanded && data.locations.length > COLLAPSED_COUNT && 'max-h-[400px] overflow-y-auto scrollable'
        )}>
          {(isListExpanded ? data.locations : data.locations.slice(0, COLLAPSED_COUNT)).map((loc, i) => {
            const isExpanded = expandedLocations.has(i);
            return (
              <div key={loc.id || i} className="border-b border-border/30 last:border-0">
                {/* Collapsed row */}
                <button
                  onClick={() => toggleLocation(i)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50 transition-colors cursor-pointer"
                >
                  {/* Number badge */}
                  <span className="w-6 h-6 rounded-full bg-[var(--color-domain-locator)]/15 text-[var(--color-domain-locator)] text-[10px] font-mono font-bold flex items-center justify-center flex-shrink-0">
                    {i + 1}
                  </span>
                  {/* Address summary */}
                  <span className="text-xs text-foreground truncate flex-1 min-w-0">
                    {formatAddressCompact(loc.address)}
                  </span>
                  {/* Phone (collapsed) */}
                  {loc.phone && (
                    <span className="text-[10px] font-mono text-muted-foreground hidden sm:block flex-shrink-0">
                      {loc.phone}
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
                    <div className="space-y-0.5 mb-2">
                      {formatAddressLines(loc.address).map((line, li) => (
                        <p key={li} className="text-xs text-foreground">{line}</p>
                      ))}
                    </div>

                    {/* Phone link */}
                    {loc.phone && (
                      <div className="flex items-center gap-1.5 mb-2">
                        <PhoneIcon className="w-3 h-3 text-muted-foreground" />
                        <a
                          href={`tel:${loc.phone}`}
                          className="text-[10px] font-mono text-[var(--color-domain-locator)] hover:underline"
                        >
                          {loc.phone}
                        </a>
                      </div>
                    )}

                    {/* Operating hours */}
                    {loc.hours && Object.keys(loc.hours).length > 0 && (
                      <div className="mt-2">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <HistoryIcon className="w-3 h-3 text-muted-foreground" />
                          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                            Hours
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                          {Object.entries(loc.hours).map(([day, hours]) => (
                            <React.Fragment key={day}>
                              <span className="text-[10px] font-mono text-muted-foreground">{day}</span>
                              <span className="text-[10px] font-mono text-foreground">{hours}</span>
                            </React.Fragment>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Show more / show less toggle */}
          {data.locations.length > COLLAPSED_COUNT && (
            <button
              onClick={() => setIsListExpanded(!isListExpanded)}
              className="w-full py-2 text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center justify-center gap-1.5 border-t border-border/30"
            >
              <ChevronDownIcon className={cn(
                'w-3.5 h-3.5 transition-transform duration-200',
                isListExpanded && 'rotate-180'
              )} />
              <span>
                {isListExpanded
                  ? 'Show less'
                  : `Show all ${data.locations.length} locations`}
              </span>
            </button>
          )}
        </div>
      )}

      {/* Service center facilities */}
      {isServiceCenters && data.facilities && data.facilities.length > 0 && (
        <div className="rounded-md border border-border/50 overflow-hidden">
          {data.facilities.map((fac, i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-2.5 border-b border-border/30 last:border-0">
              <span className="w-6 h-6 rounded-full bg-[var(--color-domain-locator)]/15 text-[var(--color-domain-locator)] text-[10px] font-mono font-bold flex items-center justify-center flex-shrink-0">
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-foreground">{fac.name}</p>
                <p className="text-[10px] font-mono text-muted-foreground">{fac.address}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
