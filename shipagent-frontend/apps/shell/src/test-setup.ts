/**
 * Test setup for the shell app.
 *
 * Installs a Map-backed localStorage shim so that stores using
 * withStorageSync (which calls localStorage.getItem / setItem) work
 * correctly in the Vitest + Node environment.
 *
 * The Angular @angular/build:unit-test executor runs tests in a Node
 * process with jsdom as the environment, but Node 25 ships with its own
 * localStorage object that requires --localstorage-file to be functional.
 * This shim overrides that stub with a real in-memory implementation.
 */

class LocalStorageShim implements Storage {
  private readonly store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }

  key(index: number): string | null {
    const keys = Array.from(this.store.keys());
    return index < keys.length ? keys[index] : null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}

// Replace the Node-provided localStorage stub with a working in-memory shim.
// This runs before any test file is imported, ensuring stores initialise cleanly.
Object.defineProperty(globalThis, 'localStorage', {
  value: new LocalStorageShim(),
  writable: true,
  configurable: true,
});
