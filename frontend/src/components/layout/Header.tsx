/**
 * Header component - Minimal branding header.
 *
 * Features:
 * - Logo and app name only
 * - Clean, minimalist design
 */

import { ShipAgentLogo } from '@/components/ui/ShipAgentLogo';

export function Header() {
  return (
    <header className="app-header">
      {/* Gradient accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-amber-500/50 to-transparent" />

      <div className="container-wide h-12 flex items-center">
        {/* Logo and branding only */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
            <ShipAgentLogo className="w-8 h-8" primaryColor="#f59e0b"  />
          </div>
          <h1 className="text-base font-semibold tracking-tight text-slate-100">
            ShipAgent
          </h1>
        </div>
      </div>
    </header>
  );
}

export default Header;
