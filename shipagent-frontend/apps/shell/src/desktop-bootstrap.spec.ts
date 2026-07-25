import { canUseTauriIpc, computeApiBaseUrl } from '@shipagent/shared-tauri';
import { handoffToSidecarShell } from './desktop-handoff';
import { startShell } from './shell-startup';

describe('production desktop bootstrap', () => {
  it('hands the packaged custom-protocol shell to the loopback sidecar', async () => {
    const replace = vi.fn();
    const invoke = vi.fn().mockResolvedValue(43123);

    const handedOff = await handoffToSidecarShell({
      location: {
        protocol: 'tauri:',
        hostname: 'localhost',
        port: '',
        replace,
      },
      invoke,
    });

    expect(handedOff).toBe(true);
    expect(invoke).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledWith('start_sidecar');
    expect(replace).toHaveBeenCalledOnce();
    expect(replace).toHaveBeenCalledWith('http://127.0.0.1:43123/');
  });

  it('does not initialize federation or Angular before the sidecar reload', async () => {
    const initializeFederation = vi.fn();
    const bootstrapAngular = vi.fn();

    const result = await startShell({
      handoffToSidecar: vi.fn().mockResolvedValue(true),
      initializeFederation,
      bootstrapAngular,
    });

    expect(result).toBe('handed-off');
    expect(initializeFederation).not.toHaveBeenCalled();
    expect(bootstrapAngular).not.toHaveBeenCalled();
  });

  it('boots once without native IPC when reloaded from the sidecar origin', async () => {
    const invoke = vi.fn();
    const replace = vi.fn();
    const initializeFederation = vi.fn();
    const bootstrapAngular = vi.fn();

    const result = await startShell({
      handoffToSidecar: () =>
        handoffToSidecarShell({
          location: {
            protocol: 'http:',
            hostname: '127.0.0.1',
            port: '43123',
            replace,
          },
          invoke,
        }),
      initializeFederation,
      bootstrapAngular,
    });

    expect(result).toBe('bootstrapped');
    expect(invoke).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(initializeFederation).toHaveBeenCalledOnce();
    expect(bootstrapAngular).toHaveBeenCalledOnce();
  });

  it('uses a relative production API URL on the sidecar-served shell', () => {
    expect(
      computeApiBaseUrl({
        protocol: 'http:',
        hostname: '127.0.0.1',
        port: '43123',
        replace: vi.fn(),
      })
    ).toBe('/api/v1');
  });

  it('does not expose desktop IPC behavior on the sidecar-served shell', () => {
    expect(
      canUseTauriIpc(
        {
          protocol: 'http:',
          hostname: '127.0.0.1',
          port: '43123',
          replace: vi.fn(),
        },
        true
      )
    ).toBe(false);
  });

  it('preserves the Native Federation development backend fallback', () => {
    expect(
      computeApiBaseUrl({
        protocol: 'http:',
        hostname: 'localhost',
        port: '4200',
        replace: vi.fn(),
      })
    ).toBe('http://localhost:8000/api/v1');
  });
});
