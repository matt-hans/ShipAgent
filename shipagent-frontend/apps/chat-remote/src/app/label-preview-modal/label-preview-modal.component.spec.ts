import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import {
  API_BASE_URL,
  ApiService,
  BrowserSessionState,
  BrowserSessionTransportService,
} from '@shipagent/shared-api';
import { LabelPreviewModalComponent } from './label-preview-modal.component';

describe('LabelPreviewModalComponent browser session transport', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('signals common session expiry when native label fetch returns 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
    });
    vi.stubGlobal('fetch', fetchMock);

    await TestBed.configureTestingModule({
      imports: [LabelPreviewModalComponent],
      providers: [
        BrowserSessionTransportService,
        { provide: API_BASE_URL, useValue: signal('/api/v1') },
        {
          provide: ApiService,
          useValue: {
            getBrowserSessionStatus: vi.fn().mockReturnValue(
              of({
                required: true,
                authenticated: false,
                csrf_token: null,
              })
            ),
          },
        },
      ],
    }).compileComponents();

    const browserSession = TestBed.inject(BrowserSessionState);
    const fixture = TestBed.createComponent(LabelPreviewModalComponent);
    fixture.componentRef.setInput('pdfUrl', '/api/v1/jobs/job-1/labels/merged');
    fixture.componentRef.setInput('isOpen', true);
    fixture.detectChanges();

    await vi.waitFor(() => {
      expect(browserSession.expirationVersion()).toBe(1);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/labels/merged',
      expect.objectContaining({ credentials: 'include' })
    );
  });
});
