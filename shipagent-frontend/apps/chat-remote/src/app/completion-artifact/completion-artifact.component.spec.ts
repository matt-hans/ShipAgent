import { TestBed } from '@angular/core/testing';
import type { ConversationMessage } from '@shipagent/shared-types';
import { CompletionArtifactComponent } from './completion-artifact.component';

function completionMessage(
  completion: Record<string, unknown>
): ConversationMessage {
  return {
    id: 'artifact-1',
    role: 'system',
    content: '',
    timestamp: '2026-07-25T00:00:00Z',
    metadata: {
      type: 'completion',
      jobId: 'job-1',
      completion: {
        jobName: 'Create shipment labels',
        successful: 0,
        failed: 0,
        totalCostCents: 0,
        ...completion,
      },
    },
  };
}

describe('CompletionArtifactComponent terminal rendering', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CompletionArtifactComponent],
    }).compileComponents();
  });

  afterEach(() => {
    TestBed.resetTestingModule();
  });

  it('renders a restored zero-count failed artifact as failed with diagnostics and no labels', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        status: 'failed',
        outcome: 'failed',
        statusMessage: 'Batch failed.',
        error: {
          code: 'BATCH_RESTORED',
          message: 'The recovered batch could not be completed.',
        },
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe('FAILED');
    expect(element.querySelector('.badge-error')).not.toBeNull();
    expect(element.querySelector('.border-l-error')).not.toBeNull();
    expect(
      Array.from(element.querySelectorAll('div')).some((div) =>
        div.classList.contains('max-h-[100px]')
      )
    ).toBe(true);
    expect(element.textContent).toContain('Batch failed.');
    expect(element.textContent).toContain(
      'BATCH_RESTORED: The recovered batch could not be completed.'
    );
    expect(element.textContent).not.toContain('View Labels');
  });

  it('does not expose labels when a completed artifact has no successful shipments', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        status: 'completed',
        outcome: 'complete',
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe(
      'COMPLETED'
    );
    expect(element.textContent).not.toContain('View Labels');
  });

  it('fails closed on labels when a failed artifact contains successful rows', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    const viewLabels = vi.fn();
    fixture.componentInstance.viewLabels.subscribe(viewLabels);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        status: 'failed',
        outcome: 'failed',
        successful: 2,
        failed: 1,
        totalCostCents: 2400,
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe('FAILED');
    expect(element.textContent).not.toContain('View Labels');
    expect(element.textContent).not.toContain('Schedule Pickup');

    fixture.componentInstance.downloadLabels();

    expect(viewLabels).not.toHaveBeenCalled();
  });

  it('retains the label action for a warning completion with successful shipments', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    const viewLabels = vi.fn();
    fixture.componentInstance.viewLabels.subscribe(viewLabels);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        status: 'completed_with_warnings',
        outcome: 'complete',
        hasWarnings: true,
        statusMessage: 'Batch completed with warnings.',
        successful: 2,
        failed: 1,
        totalCostCents: 2400,
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe(
      'COMPLETED WITH WARNINGS'
    );
    expect(element.textContent).toContain('Batch completed with warnings.');
    const labelButton = Array.from(element.querySelectorAll('button')).find(
      (button) => button.textContent?.includes('View Labels')
    );
    expect(labelButton).toBeDefined();

    labelButton?.click();

    expect(viewLabels).toHaveBeenCalledWith('job-1');
  });

  it('renders cancellation as non-success with its persisted diagnostic', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        status: 'cancelled',
        outcome: 'failed',
        cancelled: true,
        statusMessage: 'Batch cancelled. You can enter a new command.',
        error: {
          code: 'CANCELLED_RESTORED',
          message: 'Execution stopped before the batch completed.',
        },
        successful: 2,
        failed: 0,
        totalCostCents: 2400,
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe(
      'CANCELLED'
    );
    expect(element.querySelector('.badge-warning')).not.toBeNull();
    expect(element.querySelector('.border-l-warning')).not.toBeNull();
    expect(element.textContent).toContain(
      'Batch cancelled. You can enter a new command.'
    );
    expect(element.textContent).toContain(
      'CANCELLED_RESTORED: Execution stopped before the batch completed.'
    );
    expect(element.textContent).not.toContain('View Labels');
    expect(element.textContent).not.toContain('Schedule Pickup');
  });

  it('preserves row-count fallback and labels for a legacy partial artifact', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        successful: 2,
        failed: 1,
        totalCostCents: 2400,
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe(
      'PARTIAL'
    );
    expect(element.querySelector('.badge-warning')).not.toBeNull();
    expect(element.textContent).toContain('View Labels (PDF)');
  });

  it('uses canonical completion status before inconsistent row counts', () => {
    const fixture = TestBed.createComponent(CompletionArtifactComponent);
    fixture.componentRef.setInput(
      'message',
      completionMessage({
        status: 'completed',
        outcome: 'complete',
        successful: 2,
        failed: 1,
        totalCostCents: 2400,
      })
    );

    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.badge')?.textContent?.trim()).toBe(
      'COMPLETED'
    );
    expect(element.querySelector('.badge-success')).not.toBeNull();
    expect(element.textContent).toContain('View Labels (PDF)');
  });
});
