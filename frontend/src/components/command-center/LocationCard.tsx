/**
 * Inline card for UPS location search results in the chat thread.
 *
 * Renders location list (Access Points, retail, service centers)
 * with teal domain border. Accepts LocationResult as props.
 */

import { cn } from '@/lib/utils';
import type { LocationResult } from '@/types/api';
import { MapPinIcon } from '@/components/ui/icons';

function formatAddress(addr: Record<string, string>): string {
  const parts = [
    addr.AddressLine || addr.line || addr.address_line,
    [addr.City || addr.city, addr.StateProvinceCode || addr.state].filter(Boolean).join(', '),
    addr.PostalCode || addr.postal_code,
  ].filter(Boolean);
  return parts.join(' · ');
}

export function LocationCard({ data }: { data: LocationResult }) {
  const isServiceCenters = data.action === 'service_centers';
  const title = isServiceCenters ? 'UPS Service Centers' : 'UPS Locations';
  const items = isServiceCenters ? data.facilities : data.locations;
  const count = items?.length ?? 0;

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-locator')}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapPinIcon className="w-4 h-4 text-[var(--color-domain-locator)]" />
          <h4 className="text-sm font-medium text-foreground">{title}</h4>
        </div>
        <span className="badge badge-neutral">{count} found</span>
      </div>

      {count === 0 && (
        <p className="text-xs text-muted-foreground">No locations found for the given criteria.</p>
      )}

      {/* Locations list */}
      {data.locations && data.locations.length > 0 && (
        <div className="space-y-2 max-h-[200px] overflow-y-auto scrollable">
          {data.locations.map((loc, i) => (
            <div key={loc.id || i} className="px-3 py-2 rounded bg-muted space-y-1">
              <p className="text-xs font-medium text-foreground">
                {formatAddress(loc.address)}
              </p>
              {loc.phone && (
                <p className="text-[10px] font-mono text-muted-foreground">{loc.phone}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Service center facilities */}
      {isServiceCenters && data.facilities && data.facilities.length > 0 && (
        <div className="space-y-2 max-h-[200px] overflow-y-auto scrollable">
          {data.facilities.map((fac, i) => (
            <div key={i} className="px-3 py-2 rounded bg-muted space-y-1">
              <p className="text-xs font-medium text-foreground">{fac.name}</p>
              <p className="text-[10px] font-mono text-muted-foreground">{fac.address}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
