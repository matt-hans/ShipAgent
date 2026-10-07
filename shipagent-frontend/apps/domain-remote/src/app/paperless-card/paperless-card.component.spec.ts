import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import { PaperlessCardComponent } from './paperless-card.component';

describe('Paperless action preview', () => {
  it('shows the exact document/shipment and confirms the bound action directly', async () => {
    const api = { confirmWorkflowAction: vi.fn(() => of({ status: 'completed' })) };
    TestBed.configureTestingModule({ imports: [PaperlessCardComponent], providers: [
      { provide: ApiService, useValue: api }, { provide: ConversationStore, useValue: { sessionId: signal('owner') } },
    ] });
    const fixture = TestBed.createComponent(PaperlessCardComponent);
    fixture.componentRef.setInput('data', { action: 'push_preview', success: true, documentId: 'EXACT-DOC', shipmentIdentifier: 'EXACT-SHIP', session_id: 'owner', confirmation_token: 'document-action' });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('EXACT-DOC');
    expect(fixture.nativeElement.textContent).toContain('EXACT-SHIP');
    const buttons = fixture.nativeElement.querySelectorAll('button');
    expect(buttons.length).toBe(2);
    buttons[1].click(); await fixture.whenStable();
    expect(api.confirmWorkflowAction).toHaveBeenCalledExactlyOnceWith('owner', 'document-action', 'confirm');
  });
});

describe('Paperless unknown outcomes', () => {
  it.each(['uploaded', 'pushed', 'deleted'])('renders an interrupted %s without claiming success or offering retry', (action) => {
    TestBed.configureTestingModule({ imports: [PaperlessCardComponent] });
    const fixture = TestBed.createComponent(PaperlessCardComponent);
    fixture.componentRef.setInput('data', { action, success: false, outcome: 'unconfirmed', message: 'Check UPS Forms History before uploading again.' });
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Unconfirmed');
    expect(text).toContain('Check UPS Forms History');
    expect(text).not.toContain('Done');
    expect(text).not.toContain('Document Uploaded');
    expect(text).not.toContain('Document Attached');
    expect(text).not.toContain('Document Deleted');
    expect(fixture.nativeElement.querySelectorAll('button').length).toBe(0);
    expect(fixture.nativeElement.querySelector('sa-icon-check')).toBeNull();
  });
});
