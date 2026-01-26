/**
 * AppLayout - Main application layout wrapper.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';

interface AppLayoutProps {
  children: React.ReactNode;
  className?: string;
}

export function AppLayout({ children, className }: AppLayoutProps) {
  return (
    <div className={cn('app-layout', className)}>
      {children}
    </div>
  );
}

export default AppLayout;
