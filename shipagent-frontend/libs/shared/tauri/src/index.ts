/**
 * @shipagent/shared-tauri
 *
 * Tauri desktop integration utilities.
 * Provides sidecar port resolution and Tauri environment detection.
 * Only imported by the shell app — remotes should not depend on this library.
 */

export { TauriDetectionService } from './tauri-detection.service';
export { resolveSidecarPort, computeApiBaseUrl } from './port-resolver';
