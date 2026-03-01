/**
 * Platform brand icon components.
 *
 * Brand-specific glyphs for external platform integrations.
 * Import from '@/components/ui/brand-icons' instead of defining locally.
 */

export function ShopifyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="18"
        fontWeight="700"
        fill="currentColor"
      >
        S
      </text>
    </svg>
  );
}

export function AmazonIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="18"
        fontWeight="700"
        fill="currentColor"
      >
        A
      </text>
    </svg>
  );
}

export function WooCommerceIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="18"
        fontWeight="700"
        fill="currentColor"
      >
        W
      </text>
    </svg>
  );
}

export function SAPIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="16"
        fontWeight="700"
        fill="currentColor"
      >
        SAP
      </text>
    </svg>
  );
}

export function OracleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="18"
        fontWeight="700"
        fill="currentColor"
      >
        O
      </text>
    </svg>
  );
}

/** Generic platform icon fallback. */
export function PlatformIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M9 8h6M9 12h6M9 16h4" />
    </svg>
  );
}

/** DataSourceIcon with optional connected indicator dot. */
export function DataSourceIcon({ className, connected }: { className?: string; connected?: boolean }) {
  return (
    <div className="relative">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
        <ellipse cx="12" cy="6" rx="8" ry="3" />
        <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
        <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
      </svg>
      {connected && (
        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-success rounded-full" />
      )}
    </div>
  );
}
