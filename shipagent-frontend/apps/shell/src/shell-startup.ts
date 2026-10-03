export interface ShellStartupDependencies {
  initializeFederation(): Promise<unknown>;
  bootstrapAngular(): Promise<unknown>;
}

/**
 * Initialize federation, then bootstrap Angular. The packaged sidecar handoff
 * is not part of this chain: it runs from the polyfills entry (`desktop-boot`)
 * because the module-shim graph that loads `main` never starts on the
 * packaged custom-protocol origin.
 */
export async function startShell(
  dependencies: ShellStartupDependencies
): Promise<void> {
  await dependencies.initializeFederation();
  await dependencies.bootstrapAngular();
}
