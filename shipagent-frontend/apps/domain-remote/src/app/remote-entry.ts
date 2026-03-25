/**
 * Domain Remote entry point.
 *
 * Exports DomainCardRegistryService so the chat remote can dynamically
 * resolve domain card type strings to Angular component classes via
 * ngComponentOutlet — without importing domain card components directly.
 */

import { DomainCardRegistryService } from './domain-card-registry.service';

export { DomainCardRegistryService };
