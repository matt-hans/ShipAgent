/**
 * DomainCardRegistryService
 *
 * Registry that resolves domain card type strings (from SSE events) to
 * Angular component classes. Used by the chat remote via ngComponentOutlet
 * to dynamically render domain-specific result cards.
 *
 * Pattern: registry[cardType] returns Type<any> for ngComponentOutlet.
 */

import { Injectable, Type } from '@angular/core';
import { PickupPreviewComponent } from './pickup-preview/pickup-preview.component';
import { PickupCompletionComponent } from './pickup-completion/pickup-completion.component';
import { LocationCardComponent } from './location-card/location-card.component';
import { LandedCostCardComponent } from './landed-cost-card/landed-cost-card.component';
import { PaperlessCardComponent } from './paperless-card/paperless-card.component';
import { PaperlessUploadComponent } from './paperless-upload/paperless-upload.component';
import { TrackingCardComponent } from './tracking-card/tracking-card.component';
import { ContactCardComponent } from './contact-card/contact-card.component';

@Injectable()
export class DomainCardRegistryService {
  /**
   * Resolve a card type string to an Angular component class.
   * Returns null if the card type is unknown.
   */
  resolve(cardType: string): Type<unknown> | null {
    const registry: Record<string, Type<unknown>> = {
      pickup_preview: PickupPreviewComponent,
      pickup_result: PickupCompletionComponent,
      pickup_completion: PickupCompletionComponent,
      location_result: LocationCardComponent,
      landed_cost_result: LandedCostCardComponent,
      tracking_result: TrackingCardComponent,
      paperless_result: PaperlessCardComponent,
      paperless_upload: PaperlessUploadComponent,
      paperless_upload_prompt: PaperlessUploadComponent,
      contact_saved: ContactCardComponent,
    };
    return registry[cardType] ?? null;
  }
}
