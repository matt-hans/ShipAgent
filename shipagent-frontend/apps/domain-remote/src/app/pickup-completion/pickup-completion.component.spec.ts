import { TestBed } from '@angular/core/testing';
import { PickupCompletionComponent } from './pickup-completion.component';

describe('Pickup unknown outcomes', () => {
  it.each(['scheduled', 'cancelled'])('renders an interrupted %s without claiming success', (action) => {
    TestBed.configureTestingModule({ imports: [PickupCompletionComponent] });
    const fixture = TestBed.createComponent(PickupCompletionComponent);
    fixture.componentRef.setInput('data', { action, success: false, outcome: 'unconfirmed', message: 'Check its status before requesting a new action; this confirmation cannot be retried.' });
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Unconfirmed');
    expect(text).toContain('cannot be retried');
    expect(text).not.toContain('Pickup Scheduled');
    expect(text).not.toContain('Pickup Cancelled');
    expect(text).not.toContain('successfully');
    expect(text).not.toContain('CONFIRMED');
    expect(fixture.nativeElement.querySelectorAll('button').length).toBe(0);
  });
});
