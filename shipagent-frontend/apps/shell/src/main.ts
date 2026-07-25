import 'zone.js';
import { initFederation } from '@angular-architects/native-federation';
import { handoffToSidecarShell } from './desktop-handoff';
import { startShell } from './shell-startup';

startShell({
  handoffToSidecar: handoffToSidecarShell,
  initializeFederation: () => initFederation('/federation.manifest.json'),
  bootstrapAngular: () => import('./bootstrap'),
}).catch((error) => console.error(error));
