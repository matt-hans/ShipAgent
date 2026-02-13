import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { CommandCenter } from '@/components/CommandCenter';

let mockAppState: any;
let mockConversation: any;
const { mockDeleteJob } = vi.hoisted(() => ({
  mockDeleteJob: vi.fn(),
}));

vi.mock('@/hooks/useAppState', () => ({
  useAppState: () => mockAppState,
}));

vi.mock('@/hooks/useConversation', () => ({
  useConversation: () => mockConversation,
}));

vi.mock('@/components/LabelPreview', () => ({
  LabelPreview: () => null,
}));

vi.mock('@/lib/api', () => ({
  confirmJob: vi.fn(),
  cancelJob: vi.fn(),
  deleteJob: mockDeleteJob,
  getJob: vi.fn(),
  getMergedLabelsUrl: vi.fn(() => '/labels.pdf'),
  skipRows: vi.fn(),
}));

function buildBaseAppState(overrides: Record<string, unknown> = {}) {
  return {
    conversation: [],
    addMessage: vi.fn(),
    clearConversation: vi.fn(),
    isProcessing: false,
    setIsProcessing: vi.fn(),
    setActiveJob: vi.fn(),
    refreshJobList: vi.fn(),
    activeSourceType: 'shopify',
    activeSourceInfo: {
      type: 'shopify',
      label: 'Shopify',
      detail: 'mattdev',
      sourceKind: 'shopify',
    },
    warningPreference: 'ask',
    setConversationSessionId: vi.fn(),
    interactiveShipping: true,
    setInteractiveShipping: vi.fn(),
    setIsToggleLocked: vi.fn(),
    ...overrides,
  };
}

function buildBaseConversation(overrides: Record<string, unknown> = {}) {
  return {
    sessionId: null,
    events: [],
    isConnected: true,
    isProcessing: false,
    isCreatingSession: false,
    sendMessage: vi.fn(),
    reset: vi.fn(async () => {}),
    clearEvents: vi.fn(),
    ...overrides,
  };
}

describe('CommandCenter interactive mode UX', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockDeleteJob.mockReset();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });

    mockAppState = buildBaseAppState();
    mockConversation = buildBaseConversation();
  });

  it('renders interactive mode banner and hides source/settings banner', () => {
    render(<CommandCenter activeJob={null} />);

    expect(screen.queryByText('Interactive Shipping (Ad-hoc)')).not.toBeNull();
    expect(screen.queryByText('Batch commands disabled')).not.toBeNull();
    expect(screen.queryByText('Shopify')).toBeNull();
    expect(screen.queryByTitle('Shipment settings')).toBeNull();
  });

  it('shows ad-hoc welcome content only in interactive mode even when source is connected', () => {
    render(<CommandCenter activeJob={null} />);

    expect(screen.queryByText('Interactive Shipping')).not.toBeNull();
    expect(
      screen.queryByText(/Ship a 5lb box to John Smith/i)
    ).not.toBeNull();
    expect(
      screen.queryByText(/Ship all California orders using UPS Ground/i)
    ).toBeNull();
    expect(screen.queryByText(/Connected to/i)).toBeNull();
  });

  it('uses source-agnostic interactive placeholder and help text', () => {
    const { rerender } = render(<CommandCenter activeJob={null} />);

    expect(
      screen.queryByPlaceholderText('Describe one shipment from scratch...')
    ).not.toBeNull();
    expect(
      screen.queryByText(/Ad-hoc mode — provide shipment details/i)
    ).not.toBeNull();

    mockAppState = buildBaseAppState({
      activeSourceType: null,
      activeSourceInfo: null,
    });
    rerender(<CommandCenter activeJob={null} />);

    expect(
      screen.queryByPlaceholderText('Describe one shipment from scratch...')
    ).not.toBeNull();
    expect(
      screen.queryByText(/Ad-hoc mode — provide shipment details/i)
    ).not.toBeNull();
  });

  it('resets session on mode switch and clears conversation + preview', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const clearConversation = vi.fn();
    const reset = vi.fn(async () => {});

    mockAppState = buildBaseAppState({
      interactiveShipping: false,
      clearConversation,
    });
    mockConversation = buildBaseConversation({
      sessionId: 'session-1',
      reset,
      events: [
        {
          id: 'evt-1',
          type: 'preview_ready',
          data: {
            job_id: 'job-1',
            total_rows: 1,
            total_estimated_cost_cents: 1200,
            warning_count: 0,
            additional_rows: 0,
            preview_rows: [
              {
                row_number: 1,
                recipient_name: 'John Smith',
                city_state: 'Austin, TX',
                service: 'Ground',
                estimated_cost_cents: 1200,
                warnings: [],
              },
            ],
          },
          timestamp: new Date(),
        },
      ],
    });

    const { rerender } = render(<CommandCenter activeJob={null} />);

    expect(screen.queryByText('Confirm & Execute')).not.toBeNull();

    mockAppState = {
      ...mockAppState,
      interactiveShipping: true,
      clearConversation,
    };
    rerender(<CommandCenter activeJob={null} />);

    await waitFor(() => {
      expect(reset).toHaveBeenCalledTimes(1);
      expect(clearConversation).toHaveBeenCalledTimes(1);
      expect(screen.queryByText('Confirm & Execute')).toBeNull();
    });

    confirmSpy.mockRestore();
  });

  it('disables refine actions while a conversation turn is still processing', () => {
    mockConversation = buildBaseConversation({
      isProcessing: true,
      events: [
        {
          id: 'evt-1',
          type: 'preview_ready',
          data: {
            job_id: 'job-1',
            total_rows: 1,
            total_estimated_cost_cents: 1200,
            warning_count: 0,
            additional_rows: 0,
            preview_rows: [
              {
                row_number: 1,
                recipient_name: 'John Smith',
                city_state: 'Austin, TX',
                service: 'UPS Ground',
                estimated_cost_cents: 1200,
                warnings: [],
              },
            ],
          },
          timestamp: new Date(),
        },
      ],
    });

    render(<CommandCenter activeJob={null} />);

    const refineButton = screen.getByText('Refine this shipment').closest('button') as HTMLButtonElement | null;
    expect(refineButton).not.toBeNull();
    expect(refineButton?.disabled).toBe(true);
  });

  it('removes superseded pending preview job when refinement returns a new job id', async () => {
    const firstPreviewEvent = {
      id: 'evt-1',
      type: 'preview_ready',
      data: {
        job_id: 'job-1',
        total_rows: 1,
        total_estimated_cost_cents: 1200,
        warning_count: 0,
        additional_rows: 0,
        preview_rows: [
          {
            row_number: 1,
            recipient_name: 'John Smith',
            city_state: 'Austin, TX',
            service: 'UPS Ground',
            estimated_cost_cents: 1200,
            warnings: [],
          },
        ],
      },
      timestamp: new Date(),
    };

    mockConversation = buildBaseConversation({
      events: [firstPreviewEvent],
    });

    const { rerender } = render(<CommandCenter activeJob={null} />);

    expect(screen.queryByText('Confirm & Execute')).not.toBeNull();

    mockConversation = buildBaseConversation({
      events: [
        firstPreviewEvent,
        {
          ...firstPreviewEvent,
          id: 'evt-2',
          data: {
            ...firstPreviewEvent.data,
            job_id: 'job-2',
            preview_rows: [
              {
                row_number: 1,
                recipient_name: 'John Smith',
                city_state: 'Austin, TX',
                service: 'UPS Next Day Air',
                estimated_cost_cents: 3400,
                warnings: [],
              },
            ],
          },
        },
      ],
    });
    rerender(<CommandCenter activeJob={null} />);

    await waitFor(() => {
      expect(mockDeleteJob).toHaveBeenCalledWith('job-1');
    });
  });
});
