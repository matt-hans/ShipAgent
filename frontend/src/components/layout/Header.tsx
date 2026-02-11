/**
 * Header component - Minimal branding header.
 *
 * Features:
 * - Logo and app name only
 * - Clean, minimalist design
 */

import { Package } from 'lucide-react';

export function Header() {
  return (
    <header className="app-header">
      {/* Gradient accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-accent/50 to-transparent" />

      <div className="container-wide h-12 flex items-center">
        {/* Logo and branding only */}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Package className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-semibold text-foreground">ShipAgent</span>
        </div>
      </div>
    </header>
  );
}

export default Header;
