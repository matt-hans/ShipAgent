/**
 * Remote entry point for sidebar-remote.
 * Exposes SidebarContentComponent via Native Federation as './SidebarContent'.
 */

import { SidebarContentComponent } from './sidebar-content/sidebar-content.component';

export const remoteEntry = {
  component: SidebarContentComponent,
  providers: [],
};

export { SidebarContentComponent };
