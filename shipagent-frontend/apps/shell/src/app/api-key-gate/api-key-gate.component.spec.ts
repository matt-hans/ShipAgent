import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {
  API_BASE_URL,
  provideShipAgentHttpClient,
} from '@shipagent/shared-api';
import { ApiKeyGateComponent } from './api-key-gate.component';

describe('ApiKeyGateComponent', () => {
  let fixture: ComponentFixture<ApiKeyGateComponent>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApiKeyGateComponent],
      providers: [
        provideShipAgentHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: signal('/api/v1') },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ApiKeyGateComponent);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    http.verify();
  });

  async function enterKey(value: string): Promise<void> {
    const input = fixture.nativeElement.querySelector(
      'input[type="password"]'
    ) as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    await fixture.whenStable();
  }

  function submit(): void {
    const button = fixture.nativeElement.querySelector(
      'button[type="submit"]'
    ) as HTMLButtonElement;
    button.click();
    fixture.detectChanges();
  }

  it('submits the entered key and emits after authentication succeeds', async () => {
    let authenticated = false;
    fixture.componentInstance.authenticated.subscribe(() => {
      authenticated = true;
    });
    await enterKey('transient-key');

    submit();
    const request = http.expectOne('/api/v1/auth/session');
    expect(request.request.headers.get('X-API-Key')).toBe('transient-key');
    request.flush({
      required: true,
      authenticated: true,
      csrf_token: 'v1.created',
    });
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const input = fixture.nativeElement.querySelector(
      'input[type="password"]'
    ) as HTMLInputElement;
    expect(authenticated).toBe(true);
    expect(fixture.componentInstance['apiKey']()).toBe('');
    expect(input.value).toBe('');
  });

  it('clears the key and shows a generic retryable error after rejection', async () => {
    const rejectedKey = 'must-never-be-echoed';
    await enterKey(rejectedKey);

    submit();
    const request = http.expectOne('/api/v1/auth/session');
    request.flush(
      { detail: 'Invalid or missing API key' },
      { status: 401, statusText: 'Unauthorized' }
    );
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    const input = element.querySelector(
      'input[type="password"]'
    ) as HTMLInputElement;
    const button = element.querySelector(
      'button[type="submit"]'
    ) as HTMLButtonElement;
    expect(fixture.componentInstance['apiKey']()).toBe('');
    expect(input.value).toBe('');
    expect(element.textContent).toContain(
      'Authentication failed. Check the API key and try again.'
    );
    expect(element.textContent).not.toContain(rejectedKey);
    expect(input.disabled).toBe(false);
    expect(button.disabled).toBe(true);

    await enterKey('replacement-key');
    expect(button.disabled).toBe(false);
  });

  it('does not submit an empty key', () => {
    submit();

    http.expectNone('/api/v1/auth/session');
  });
});
