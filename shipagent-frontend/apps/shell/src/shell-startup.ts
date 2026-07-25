export interface ShellStartupDependencies {
  handoffToSidecar(): Promise<boolean>;
  initializeFederation(): Promise<unknown>;
  bootstrapAngular(): Promise<unknown>;
}

export type ShellStartupResult = 'handed-off' | 'bootstrapped';

/**
 * Run the production sidecar handoff before any federation or Angular work.
 */
export async function startShell(
  dependencies: ShellStartupDependencies
): Promise<ShellStartupResult> {
  if (await dependencies.handoffToSidecar()) {
    return 'handed-off';
  }

  await dependencies.initializeFederation();
  await dependencies.bootstrapAngular();
  return 'bootstrapped';
}
