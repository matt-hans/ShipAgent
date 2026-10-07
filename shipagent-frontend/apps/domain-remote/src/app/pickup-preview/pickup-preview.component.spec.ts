import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, Subject } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import type { PickupPreview } from '@shipagent/shared-types';
import { PickupPreviewComponent } from './pickup-preview.component';

const preview = {
  session_id: 'owner', confirmation_token: 'opaque-preview', action: 'schedule',
  address_line: '12 Test Road', city: 'Oakland', state: 'CA', postal_code: '94612',
  country_code: 'US', pickup_date: '20261008', ready_time: '0900', close_time: '1700',
  pickup_type: 'oncall', contact_name: 'Synthetic', phone_number: '5550100',
  charges: [], grand_total: '7.50',
} as PickupPreview;

describe('Pickup preview user authority', () => {
  function setup(data = preview) {
    const response = new Subject<{ status: string }>();
    const sessionId = signal('owner');
    const api = { confirmWorkflowAction: vi.fn(() => response), sendMessage: vi.fn(() => of({})), };
    TestBed.configureTestingModule({ imports: [PickupPreviewComponent], providers: [
      { provide: ApiService, useValue: api },
      { provide: ConversationStore, useValue: { sessionId, setStreaming: vi.fn(), appendMessage: vi.fn() } },
    ] });
    const fixture = TestBed.createComponent(PickupPreviewComponent);
    fixture.componentRef.setInput('data', data);
    fixture.detectChanges();
    const buttons = () => Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    return { fixture, buttons, api, response, sessionId };
  }

  it('confirms once using the bound endpoint and never sends authority to the model', async () => {
    const { fixture, buttons, api, response } = setup();
    buttons()[1].click();
    fixture.detectChanges();
    buttons()[1].click();
    expect(api.confirmWorkflowAction).toHaveBeenCalledExactlyOnceWith('owner', 'opaque-preview', 'confirm');
    expect(api.sendMessage).not.toHaveBeenCalled();
    response.next({ status: 'completed' }); response.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(buttons()[1].disabled).toBe(true);
  });

  it('Cancel revokes server authority and disables the old preview', async () => {
    const { fixture, buttons, api, response } = setup();
    buttons()[0].click();
    expect(api.confirmWorkflowAction).toHaveBeenCalledExactlyOnceWith('owner', 'opaque-preview', 'cancel');
    response.next({ status: 'cancelled' }); response.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(buttons().every(button => button.disabled)).toBe(true);
  });

  it('old-session and legacy tokenless previews cannot be confirmed', () => {
    const { fixture, buttons, api, sessionId } = setup();
    sessionId.set('another-session'); fixture.detectChanges();
    expect(buttons().every(button => button.disabled)).toBe(true);
    buttons()[1].click();
    expect(api.confirmWorkflowAction).not.toHaveBeenCalled();
    sessionId.set('owner'); fixture.componentRef.setInput('data', { ...preview, confirmation_token: undefined }); fixture.detectChanges();
    expect(buttons()[1].disabled).toBe(true);
  });

  it('an ambiguous failure keeps the consumed preview disabled and asks for status verification', async () => {
    const { fixture, buttons, api, response } = setup();
    buttons()[1].click();
    response.error({ status: 502, error: { detail: 'Carrier outcome is unconfirmed. Check its status before requesting a new action.' } });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Check');
    expect(buttons().every(button => button.disabled)).toBe(true);
    expect(api.confirmWorkflowAction).toHaveBeenCalledTimes(1);
  });
});
