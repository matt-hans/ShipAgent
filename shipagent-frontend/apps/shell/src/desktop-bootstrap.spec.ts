import { canUseTauriIpc, computeApiBaseUrl } from '@shipagent/shared-tauri';
import { handoffToSidecarShell, runDesktopBoot } from './desktop-handoff';
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

  it('reports a visible error instead of a blank window when the sidecar fails', async () => {
    const root = { textContent: '' };
    const report = vi.fn();

    await runDesktopBoot({
      location: {
        protocol: 'tauri:',
        hostname: 'localhost',
        port: '',
        replace: vi.fn(),
      },
      invoke: vi.fn().mockRejectedValue('Backend binary not found'),
      root,
      report,
    });

    expect(root.textContent).toContain('Backend binary not found');
    expect(report).toHaveBeenCalledOnce();
  });

  it('leaves the document untouched when the boot hands off or is not packaged', async () => {
    const root = { textContent: 'unchanged' };
    const invoke = vi.fn();

    await runDesktopBoot({
      location: {
        protocol: 'http:',
        hostname: '127.0.0.1',
        port: '43123',
        replace: vi.fn(),
      },
      invoke,
      root,
      report: vi.fn(),
    });

    expect(invoke).not.toHaveBeenCalled();
    expect(root.textContent).toBe('unchanged');
  });

  it('always initializes federation and Angular on the normal shell path', async () => {
    const initializeFederation = vi.fn();
    const bootstrapAngular = vi.fn();

    await startShell({ initializeFederation, bootstrapAngular });

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

  it('uses the relative API URL through the Native Federation dev proxy', () => {
    expect(
      computeApiBaseUrl({
        protocol: 'http:',
        hostname: 'localhost',
        port: '4200',
        replace: vi.fn(),
      })
    ).toBe('/api/v1');
  });
});
