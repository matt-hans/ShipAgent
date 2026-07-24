import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {
  API_BASE_URL,
  ApiService,
  BrowserSessionState,
  provideShipAgentHttpClient,
} from '@shipagent/shared-api';

describe('browser session HTTP', () => {
  let api: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideShipAgentHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: signal('/api/v1') },
      ],
    });
    api = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('uses browser credentials without adding an API key to normal requests', () => {
    api.getSettings().subscribe();

    const request = http.expectOne('/api/v1/settings');
    expect(request.request.withCredentials).toBe(true);
    expect(request.request.headers.has('X-API-Key')).toBe(false);
    request.flush({});
  });

  it('adds the entered key only to browser session creation', () => {
    api.createBrowserSession('runtime-only-key').subscribe();

    const request = http.expectOne('/api/v1/auth/session');
    expect(request.request.method).toBe('POST');
    expect(request.request.withCredentials).toBe(true);
    expect(request.request.headers.get('X-API-Key')).toBe('runtime-only-key');
    request.flush({ required: true, authenticated: true });
  });

  it('reads and clears browser sessions without an API key header', () => {
    api.getBrowserSessionStatus().subscribe();
    const status = http.expectOne('/api/v1/auth/session');
    expect(status.request.method).toBe('GET');
    expect(status.request.headers.has('X-API-Key')).toBe(false);
    status.flush({ required: true, authenticated: false });

    api.clearBrowserSession().subscribe();
    const clear = http.expectOne('/api/v1/auth/session');
    expect(clear.request.method).toBe('DELETE');
    expect(clear.request.headers.has('X-API-Key')).toBe(false);
    clear.flush({ required: true, authenticated: false });
  });

  it('signals protected 401 responses but excludes every session flow', () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    expect(browserSession.expirationVersion()).toBe(0);

    api.getSettings().subscribe({ error: () => undefined });
    http.expectOne('/api/v1/settings').flush(
      { detail: 'Expired' },
      { status: 401, statusText: 'Unauthorized' },
    );
    expect(browserSession.expirationVersion()).toBe(1);

    api.getBrowserSessionStatus().subscribe({ error: () => undefined });
    http.expectOne('/api/v1/auth/session').flush(
      { detail: 'Unavailable' },
      { status: 401, statusText: 'Unauthorized' },
    );

    api.createBrowserSession('replacement').subscribe({
      error: () => undefined,
    });
    http.expectOne('/api/v1/auth/session').flush(
      { detail: 'Rejected' },
      { status: 401, statusText: 'Unauthorized' },
    );

    api.clearBrowserSession().subscribe({ error: () => undefined });
    http.expectOne('/api/v1/auth/session').flush(
      { detail: 'Unavailable' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(browserSession.expirationVersion()).toBe(1);
  });
});
