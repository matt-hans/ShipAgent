/**
 * AppLayout - Main application layout with navigation.
 *
 * Provides the header, navigation tabs, and content area structure
 * for the ShipAgent application.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';

export type AppTab = 'shipments' | 'sources';

interface AppLayoutProps {
  children: React.ReactNode;
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
}

/** Package icon for shipments. */
function PackageIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="m7.5 4.27 9 5.15" />
      <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
      <path d="m3.3 7 8.7 5 8.7-5" />
      <path d="M12 22V12" />
    </svg>
  );
}

/** Database/sources icon. */
function DatabaseIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5v14a9 3 0 0 0 18 0V5" />
      <path d="M3 12a9 3 0 0 0 18 0" />
    </svg>
  );
}

/** ShipAgent logo. */
function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-accent-foreground" />
      </div>
      <div>
        <h1 className="text-lg font-semibold tracking-tight leading-none">
          ShipAgent
        </h1>
        <p className="text-[10px] text-muted-foreground leading-none mt-0.5">
          Batch Shipment Processing
        </p>
      </div>
    </div>
  );
}

/** Navigation tab button. */
function NavTab({
  label,
  icon,
  isActive,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'nav-tab flex items-center gap-2',
        isActive && 'nav-tab--active'
      )}
      type="button"
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

/**
 * AppLayout component providing the main application structure.
 *
 * Features:
 * - Sticky header with logo and navigation
 * - Tab-based navigation between shipments and data sources
 * - Responsive content area
 */
export function AppLayout({ children, activeTab, onTabChange }: AppLayoutProps) {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="page-header">
        <div className="container mx-auto px-4">
          {/* Top row: Logo */}
          <div className="py-4 flex items-center justify-between">
            <Logo />
          </div>

          {/* Navigation tabs */}
          <nav className="flex gap-1 -mb-px">
            <NavTab
              label="Shipments"
              icon={<PackageIcon className="w-4 h-4" />}
              isActive={activeTab === 'shipments'}
              onClick={() => onTabChange('shipments')}
            />
            <NavTab
              label="Data Sources"
              icon={<DatabaseIcon className="w-4 h-4" />}
              isActive={activeTab === 'sources'}
              onClick={() => onTabChange('sources')}
            />
          </nav>
        </div>
      </header>

      {/* Main content */}
      <main className="container mx-auto px-4 py-8 max-w-5xl">
        {children}
      </main>
    </div>
  );
}

export default AppLayout;
