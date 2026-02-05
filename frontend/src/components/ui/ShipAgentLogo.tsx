/**
 * ShipAgent Logo - Clean shipping parcel/package.
 *
 * A minimalist logo representing a shipping cardboard box
 * with packing tape - clean and recognizable.
 */

interface ShipAgentLogoProps {
  className?: string;
  /** Primary color for the package */
  primaryColor?: string;
}

export function ShipAgentLogo({
  className,
  primaryColor = '#f59e0b',
}: ShipAgentLogoProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className}>
      {/* Cardboard shipping box */}
      <g>
        {/* Main box front face */}
        <rect
          x="6"
          y="16"
          width="28"
          height="22"
          rx="1.5"
          fill={primaryColor}
          fillOpacity="0.15"
          stroke={primaryColor}
          strokeWidth="2"
        />

        {/* Box right side (3D depth) */}
        <path
          d="M34 16L42 12V32L34 38V16Z"
          fill={primaryColor}
          fillOpacity="0.08"
          stroke={primaryColor}
          strokeWidth="2"
          strokeLinejoin="round"
        />

        {/* Box top face */}
        <path
          d="M6 16L14 10H34L42 12L34 16H6Z"
          fill={primaryColor}
          fillOpacity="0.1"
          stroke={primaryColor}
          strokeWidth="2"
          strokeLinejoin="round"
        />

        {/* Packing tape - center vertical strip on top */}
        <path
          d="M20 10V16"
          stroke={primaryColor}
          strokeWidth="4"
          strokeLinecap="butt"
          opacity="0.35"
        />

        {/* Packing tape - continues down front */}
        <path
          d="M20 16V38"
          stroke={primaryColor}
          strokeWidth="4"
          strokeLinecap="butt"
          opacity="0.25"
        />

        {/* Box flap seam lines on top */}
        <path
          d="M14 10L20 13L34 10"
          stroke={primaryColor}
          strokeWidth="1.5"
          strokeLinecap="round"
          opacity="0.4"
        />
      </g>
    </svg>
  );
}

/** Compact version for small spaces - just the package */
export function ShipAgentIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      {/* Simple parcel box */}
      <rect
        x="3"
        y="7"
        width="14"
        height="12"
        rx="1"
        fill="currentColor"
        fillOpacity="0.15"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      {/* 3D side */}
      <path
        d="M17 7L21 5V15L17 19V7Z"
        fill="currentColor"
        fillOpacity="0.08"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {/* Top flap */}
      <path
        d="M3 7L10 4L17 7"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M17 7L21 5" stroke="currentColor" strokeWidth="1.5" />
      {/* Tape */}
      <line x1="10" y1="4" x2="10" y2="7" stroke="currentColor" strokeWidth="2" opacity="0.5" />
    </svg>
  );
}

export default ShipAgentLogo;
