import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';

@Component({
  selector: 'app-api-key-gate',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <main
      class="h-screen bg-background flex items-center justify-center p-6"
      aria-labelledby="api-key-gate-title"
    >
      <section
        class="w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-2xl"
      >
        <div
          class="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground font-semibold"
          aria-hidden="true"
        >
          SA
        </div>
        <h1
          id="api-key-gate-title"
          class="text-center text-xl font-semibold text-foreground"
        >
          Unlock ShipAgent
        </h1>
        <p class="mt-2 text-center text-sm text-muted-foreground">
          Enter the API key configured for this Docker deployment. It is used
          only for this session exchange and is not stored by the app.
        </p>

        <form class="mt-6 space-y-4" (ngSubmit)="submit()">
          <div class="space-y-2">
            <label
              for="docker-api-key"
              class="block text-sm font-medium text-foreground"
            >
              Docker API key
            </label>
            <input
              id="docker-api-key"
              name="dockerApiKey"
              type="password"
              autocomplete="off"
              data-1p-ignore
              spellcheck="false"
              [ngModel]="apiKey()"
              (ngModelChange)="apiKey.set($event)"
              [disabled]="submitting()"
              aria-describedby="api-key-help api-key-error"
              class="w-full rounded-lg border border-input bg-background px-3 py-2 text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            />
            <p id="api-key-help" class="text-xs text-muted-foreground">
              Find this value in the <code>SHIPAGENT_API_KEY</code> setting
              used to start the container.
            </p>
          </div>

          @if (authenticationFailed()) {
            <p
              id="api-key-error"
              role="alert"
              class="text-sm text-destructive"
            >
              Authentication failed. Check the API key and try again.
            </p>
          }

          <button
            type="submit"
            [disabled]="!apiKey().trim() || submitting()"
            class="btn-primary w-full rounded-lg px-4 py-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {{ submitting() ? 'Unlocking…' : 'Unlock ShipAgent' }}
          </button>
        </form>
      </section>
    </main>
  `,
})
export class ApiKeyGateComponent {
  private readonly api = inject(ApiService);

  @Output() readonly authenticated = new EventEmitter<void>();

  protected readonly apiKey = signal('');
  protected readonly submitting = signal(false);
  protected readonly authenticationFailed = signal(false);

  protected submit(): void {
    const candidate = this.apiKey().trim();
    if (!candidate || this.submitting()) return;

    this.submitting.set(true);
    this.authenticationFailed.set(false);
    this.api
      .createBrowserSession(candidate)
      .pipe(
        finalize(() => {
          this.apiKey.set('');
          this.submitting.set(false);
        }),
      )
      .subscribe({
        next: () => this.authenticated.emit(),
        error: () => this.authenticationFailed.set(true),
      });
  }
}
