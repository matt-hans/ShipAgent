import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {
  API_BASE_URL,
  ApiService,
  BrowserSessionState,
  BrowserSessionTransportService,
  provideShipAgentHttpClient,
} from '@shipagent/shared-api';

describe('browser session HTTP', () => {
  let api: ApiService;
  let rawHttp: HttpClient;
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
    rawHttp = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.unstubAllGlobals();
  });

  it('uses browser credentials without adding an API key to normal requests', () => {
    api.getSettings().subscribe();

    const request = http.expectOne('/api/v1/settings');
    expect(request.request.withCredentials).toBe(true);
    expect(request.request.headers.has('X-API-Key')).toBe(false);
    request.flush({});
  });

  it('adds the entered key only to browser session creation', () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    api.createBrowserSession('runtime-only-key').subscribe();

    const request = http.expectOne('/api/v1/auth/session');
    expect(request.request.method).toBe('POST');
    expect(request.request.withCredentials).toBe(true);
    expect(request.request.headers.get('X-API-Key')).toBe('runtime-only-key');
    expect(request.request.headers.has('X-CSRF-Token')).toBe(false);
    request.flush({
      required: true,
      authenticated: true,
      csrf_token: 'v1.session-bound',
    });
    expect(browserSession.csrfToken()).toBe('v1.session-bound');
  });

  it('reads and clears browser sessions without an API key header', () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    api.getBrowserSessionStatus().subscribe();
    const status = http.expectOne('/api/v1/auth/session');
    expect(status.request.method).toBe('GET');
    expect(status.request.headers.has('X-API-Key')).toBe(false);
    expect(status.request.headers.has('X-CSRF-Token')).toBe(false);
    status.flush({
      required: true,
      authenticated: true,
      csrf_token: 'v1.recovered',
    });
    expect(browserSession.csrfToken()).toBe('v1.recovered');

    api.clearBrowserSession().subscribe();
    const clear = http.expectOne('/api/v1/auth/session');
    expect(clear.request.method).toBe('DELETE');
    expect(clear.request.headers.has('X-API-Key')).toBe(false);
    expect(clear.request.headers.has('X-CSRF-Token')).toBe(false);
    clear.flush({
      required: true,
      authenticated: false,
      csrf_token: null,
    });
    expect(browserSession.csrfToken()).toBeNull();
  });

  it('adds the in-memory CSRF token only to unsafe non-session requests', () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    browserSession.applySessionStatus({
      required: true,
      authenticated: true,
      csrf_token: 'v1.memory-only',
    });

    api.getSettings().subscribe();
    const safe = http.expectOne('/api/v1/settings');
    expect(safe.request.headers.has('X-CSRF-Token')).toBe(false);
    safe.flush({});

    api.createConversation().subscribe();
    const unsafe = http.expectOne('/api/v1/conversations/');
    expect(unsafe.request.headers.get('X-CSRF-Token')).toBe('v1.memory-only');
    unsafe.flush({ session_id: 'session-1', interactive_shipping: false });

    rawHttp.post('https://example.test/api/v1/webhook', {}).subscribe();
    const external = http.expectOne('https://example.test/api/v1/webhook');
    expect(external.request.headers.has('X-CSRF-Token')).toBe(false);
    external.flush({});
  });

  it('signals protected 401 responses but excludes every session flow', () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    browserSession.applySessionStatus({
      required: true,
      authenticated: true,
      csrf_token: 'v1.expiring',
    });
    expect(browserSession.expirationVersion()).toBe(0);

    api.getSettings().subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/settings')
      .flush(
        { detail: 'Expired' },
        { status: 401, statusText: 'Unauthorized' }
      );
    expect(browserSession.expirationVersion()).toBe(1);
    expect(browserSession.csrfToken()).toBeNull();

    api.getBrowserSessionStatus().subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/auth/session')
      .flush(
        { detail: 'Unavailable' },
        { status: 401, statusText: 'Unauthorized' }
      );

    api.createBrowserSession('replacement').subscribe({
      error: () => undefined,
    });
    http
      .expectOne('/api/v1/auth/session')
      .flush(
        { detail: 'Rejected' },
        { status: 401, statusText: 'Unauthorized' }
      );

    api.clearBrowserSession().subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/auth/session')
      .flush(
        { detail: 'Unavailable' },
        { status: 401, statusText: 'Unauthorized' }
      );

    expect(browserSession.expirationVersion()).toBe(1);
  });

  it('keeps native fetch credentials and CSRF scoped to ShipAgent mutations', async () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    browserSession.applySessionStatus({
      required: true,
      authenticated: true,
      csrf_token: 'v1.native-memory',
    });
    const fetchMock = vi.fn().mockResolvedValue({ status: 200 });
    vi.stubGlobal('fetch', fetchMock);
    const transport = TestBed.inject(BrowserSessionTransportService);

    await transport.fetch('/api/v1/settings', { method: 'PATCH' });
    await transport.fetch('https://example.test/api/v1/webhook', {
      method: 'POST',
    });

    const apiInit = fetchMock.mock.calls[0][1] as RequestInit;
    const externalInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(apiInit.credentials).toBe('include');
    expect(new Headers(apiInit.headers).get('X-CSRF-Token')).toBe(
      'v1.native-memory'
    );
    expect(externalInit.credentials).toBe('include');
    expect(new Headers(externalInit.headers).has('X-CSRF-Token')).toBe(false);
  });
});
