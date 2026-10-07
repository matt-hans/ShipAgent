import { TestBed } from '@angular/core/testing';
import { BatchPreviewComponent } from './batch-preview.component';

describe('BatchPreviewComponent priced confirmation', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({imports: [BatchPreviewComponent]}).compileComponents();
  });
  afterEach(() => TestBed.resetTestingModule());

  it.each([false, true])('only permits confirmation of a priced preview: %s', (ready) => {
    const fixture = TestBed.createComponent(BatchPreviewComponent);
    fixture.componentRef.setInput('preview', {
      job_id: 'job-1', total_rows: 1, preview_rows: [], additional_rows: 1,
      total_estimated_cost_cents: 0, rows_with_warnings: ready ? 0 : 1,
      confirmation_ready: ready,
    });
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const confirm = Array.from(element.querySelectorAll('button')).find(button => button.textContent?.includes('Confirm & Execute'));
    expect(confirm?.disabled).toBe(!ready);
    const refine = Array.from(element.querySelectorAll('button')).find(button => button.textContent?.trim() === 'Refine');
    expect(refine?.disabled).toBe(false);
    if (!ready) expect(element.textContent).toContain('Re-preview');
  });
});
