/**
 * Conversation-related test fixtures.
 */

import type {
  ChatSessionSummary,
  PersistedMessage,
  SessionDetail,
  CreateConversationResponse,
  SendMessageResponse,
} from '@shipagent/shared-types';

export const conversationFixtures = {
  /** A single chat session summary. */
  chatSession: (): ChatSessionSummary => ({
    id: 'session-001',
    title: 'Ship California Orders',
    mode: 'batch',
    created_at: '2026-03-24T10:00:00Z',
    updated_at: '2026-03-24T10:05:00Z',
    message_count: 4,
  }),

  /** Multiple chat sessions for sidebar display. */
  chatSessionList: (): ChatSessionSummary[] => [
    {
      id: 'session-001',
      title: 'Ship California Orders',
      mode: 'batch',
      created_at: '2026-03-24T10:00:00Z',
      updated_at: '2026-03-24T10:05:00Z',
      message_count: 4,
    },
    {
      id: 'session-002',
      title: 'Track package 1Z999...',
      mode: 'interactive',
      created_at: '2026-03-23T14:00:00Z',
      updated_at: '2026-03-23T14:10:00Z',
      message_count: 6,
    },
  ],

  /** A persisted message (user). */
  userMessage: (): PersistedMessage => ({
    id: 'msg-001',
    role: 'user',
    message_type: 'text',
    content: 'Ship all California orders via UPS Ground',
    metadata: null,
    sequence: 1,
    created_at: '2026-03-24T10:00:00Z',
  }),

  /** A persisted message (assistant). */
  assistantMessage: (): PersistedMessage => ({
    id: 'msg-002',
    role: 'assistant',
    message_type: 'text',
    content: 'I found 25 orders from California. The estimated cost is $312.50. Shall I proceed?',
    metadata: null,
    sequence: 2,
    created_at: '2026-03-24T10:01:00Z',
  }),

  /** A full session detail with messages. */
  sessionDetail: (): SessionDetail => ({
    session: {
      id: 'session-001',
      title: 'Ship California Orders',
      mode: 'batch',
      created_at: '2026-03-24T10:00:00Z',
      updated_at: '2026-03-24T10:05:00Z',
      message_count: 2,
    },
    messages: [
      {
        id: 'msg-001',
        role: 'user',
        message_type: 'text',
        content: 'Ship all California orders via UPS Ground',
        metadata: null,
        sequence: 1,
        created_at: '2026-03-24T10:00:00Z',
      },
      {
        id: 'msg-002',
        role: 'assistant',
        message_type: 'text',
        content: 'I found 25 orders from California...',
        metadata: null,
        sequence: 2,
        created_at: '2026-03-24T10:01:00Z',
      },
    ],
  }),

  /** Create conversation response. */
  createConversationResponse: (): CreateConversationResponse => ({
    session_id: 'session-001',
    interactive_shipping: false,
  }),

  /** Send message response. */
  sendMessageResponse: (): SendMessageResponse => ({
    status: 'accepted',
    session_id: 'session-001',
  }),

  /** SSE event payloads for each event type. */
  sseEvents: {
    agentThinking: () => ({
      event: 'agent_thinking' as const,
      data: {},
    }),

    agentMessage: (content = 'Hello, I can help you ship your orders.') => ({
      event: 'agent_message' as const,
      data: { content },
    }),

    agentMessageDelta: (delta = ' orders') => ({
      event: 'agent_message_delta' as const,
      data: { delta },
    }),

    previewReady: (jobId = 'job-001') => ({
      event: 'preview_ready' as const,
      data: {
        job_id: jobId,
        total_rows: 25,
        preview_rows: [
          {
            row_number: 1,
            recipient_name: 'Alice Johnson',
            city_state: 'Los Angeles, CA',
            service: 'UPS Ground',
            estimated_cost_cents: 1250,
            warnings: [],
          },
        ],
        additional_rows: 24,
        total_estimated_cost_cents: 31250,
        rows_with_warnings: 0,
      },
    }),

    executionProgress: (jobId = 'job-001', processed = 5, total = 25) => ({
      event: 'execution_progress' as const,
      data: { job_id: jobId, processed, total, failed: 0 },
    }),

    completion: (jobId = 'job-001') => ({
      event: 'completion' as const,
      data: {
        job_id: jobId,
        successful: 25,
        total_cost_cents: 31250,
      },
    }),

    error: (message = 'An error occurred') => ({
      event: 'error' as const,
      data: { message, error_code: 'E-9999' },
    }),

    done: () => ({
      event: 'done' as const,
      data: {},
    }),

    pickupPreview: () => ({
      event: 'pickup_preview' as const,
      data: {
        address_line: '123 Main St',
        city: 'Los Angeles',
        state: 'CA',
        postal_code: '90001',
        country_code: 'US',
        pickup_date: '2026-03-25',
        ready_time: '09:00',
        close_time: '17:00',
        pickup_type: 'Daily Pickup',
        contact_name: 'John Doe',
        phone_number: '555-0100',
        charges: [
          { chargeCode: 'PICKUP', chargeLabel: 'Pickup Fee', chargeAmount: '5.00' },
        ],
        grand_total: '5.00',
      },
    }),

    trackingResult: (trackingNumber = '1Z999AA10123456784') => ({
      event: 'tracking_result' as const,
      data: {
        action: 'tracked',
        success: true,
        trackingNumber,
        currentStatus: 'IN_TRANSIT',
        statusDescription: 'Package is in transit',
        deliveryDate: '2026-03-26',
        activities: [
          {
            date: '2026-03-24',
            time: '10:00',
            location: 'Los Angeles, CA',
            status: 'Departed facility',
          },
        ],
      },
    }),
  },
};
