import { ChangeDetectionStrategy, Component, Input, OnChanges, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import type { WorkflowConfirmation } from '@shipagent/shared-types';

/** A real user gesture references an immutable server action; no model message. */
@Component({
  selector: 'app-workflow-confirmation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (message()) { <p class="text-xs mb-3" role="status">{{ message() }}</p> }
    @if (!data.confirmation_token || !data.session_id) {
      <p class="text-xs mb-3">Request a new preview to confirm this action.</p>
    }
    <div class="flex gap-3">
      <button class="btn-secondary flex-1 h-9 text-sm" (click)="decide('cancel')" [disabled]="disabled()">Cancel</button>
      <button class="btn-primary flex-1 h-9 text-sm" (click)="decide('confirm')" [disabled]="disabled()">
        {{ busy() ? 'Submitting...' : confirmLabel }}
      </button>
    </div>
  `,
})
export class WorkflowConfirmationComponent implements OnChanges {
  @Input({ required: true }) data!: WorkflowConfirmation;
  @Input() confirmLabel = 'Confirm';
  private readonly api = inject(ApiService);
  private readonly conversation = inject(ConversationStore);
  private readonly attempted = new Set<string>();
  readonly busy = signal(false);
  readonly message = signal('');

  ngOnChanges(): void { this.message.set(''); }

  disabled(): boolean {
    return this.busy() || !this.data.confirmation_token || !this.data.session_id
      || this.data.session_id !== this.conversation.sessionId()
      || this.attempted.has(this.data.confirmation_token);
  }

  async decide(decision: 'confirm' | 'cancel'): Promise<void> {
    if (this.disabled()) return;
    const token = this.data.confirmation_token!;
    const sessionId = this.data.session_id!;
    this.attempted.add(token);
    this.busy.set(true);
    try {
      const result = await firstValueFrom(this.api.confirmWorkflowAction(sessionId, token, decision));
      if (this.data.confirmation_token === token && this.conversation.sessionId() === sessionId) {
        this.message.set(result.status === 'cancelled' ? 'Cancelled' : 'Completed');
      }
    } catch (error: unknown) {
      if (this.data.confirmation_token === token && this.conversation.sessionId() === sessionId) {
        const status = (error as { status?: number })?.status;
        this.message.set(status === 409
          ? 'This preview is no longer available. Request a new preview.'
          : 'Outcome is unconfirmed. Check carrier status before requesting a new action.');
      }
    } finally {
      this.busy.set(false);
    }
  }
}
