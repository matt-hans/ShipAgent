/**
 * Auto-update checker for the Tauri desktop app.
 *
 * Checks for updates on mount and every 4 hours. Shows a non-intrusive
 * banner when an update is available, with "Update Now" and "Later" buttons.
 * Only renders inside Tauri — hidden in Vite dev mode.
 */

import { useEffect, useState } from 'react';

interface UpdateInfo {
  version: string;
  body: string;
}

export function UpdateChecker() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    if (!(window as any).__TAURI__) return;

    async function checkForUpdate() {
      try {
        const { check } = await import('@tauri-apps/plugin-updater');
        const result = await check();
        if (result?.available) {
          setUpdate({
            version: result.version,
            body: result.body ?? 'Bug fixes and improvements.',
          });
        }
      } catch (err) {
        console.warn('Update check failed:', err);
      }
    }

    checkForUpdate();
    const interval = setInterval(checkForUpdate, 4 * 60 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (!update) return null;

  async function handleInstall() {
    setInstalling(true);
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const result = await check();
      if (result?.available) {
        await result.downloadAndInstall();
      }
    } catch (err) {
      console.error('Update install failed:', err);
      setInstalling(false);
    }
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm rounded-lg border
                    border-cyan-500/30 bg-gray-900 p-4 shadow-lg">
      <p className="text-sm font-medium text-white">
        ShipAgent {update.version} is available
      </p>
      <p className="mt-1 text-xs text-gray-400 line-clamp-2">{update.body}</p>
      <div className="mt-3 flex gap-2">
        <button
          onClick={handleInstall}
          disabled={installing}
          className="btn-primary text-xs"
        >
          {installing ? 'Installing...' : 'Update Now'}
        </button>
        <button
          onClick={() => setUpdate(null)}
          className="btn-secondary text-xs"
        >
          Later
        </button>
      </div>
    </div>
  );
}
