interface DesktopBootstrapLocation {
  readonly protocol: string;
  readonly hostname: string;
  readonly port: string;
  replace(url: string): void;
}

type TauriInvoke = (command: string) => Promise<unknown>;

interface SidecarHandoffOptions {
  readonly location?: DesktopBootstrapLocation;
  readonly invoke?: TauriInvoke;
}

function isPackagedTauriOrigin(location: DesktopBootstrapLocation): boolean {
  return (
    location.protocol === 'tauri:' ||
    (location.protocol === 'http:' && location.hostname === 'tauri.localhost')
  );
}

function globalTauriInvoke(): TauriInvoke {
  const tauriWindow = window as Window & {
    __TAURI__?: { core?: { invoke?: TauriInvoke } };
  };
  const invoke = tauriWindow.__TAURI__?.core?.invoke;
  if (!invoke) {
    throw new Error('Tauri command API is unavailable on the packaged origin');
  }
  return invoke;
}

/**
 * Start the packaged sidecar from trusted custom-protocol content, then replace
 * that bootstrap document with the same shell served by the sidecar.
 *
 * This module stays local to the shell so the pre-federation entry point has no
 * mapped-workspace imports. Sidecar, development, and ordinary web origins
 * return false without attempting native IPC.
 */
export async function handoffToSidecarShell(
  options: SidecarHandoffOptions = {}
): Promise<boolean> {
  const location = options.location ?? window.location;
  if (!isPackagedTauriOrigin(location)) {
    return false;
  }

  const port = Number(
    await (options.invoke ?? globalTauriInvoke())('start_sidecar')
  );
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error(`Sidecar reported invalid port: ${port}`);
  }

  location.replace(`http://127.0.0.1:${port}/`);
  return true;
}
