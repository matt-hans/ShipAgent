import 'zone.js';
import { initFederation } from '@angular-architects/native-federation';
import { startShell } from './shell-startup';

startShell({
  initializeFederation: () => initFederation('/federation.manifest.json'),
  bootstrapAngular: () => import('./bootstrap'),
}).catch((error) => console.error(error));
