// Preloaded via NODE_OPTIONS=--require for production frontend builds.
//
// @angular/build (CommonJS under Nx) loads the ESM-only @angular/compiler-cli
// with require() while native-federation's shared-package bundling import()s
// it concurrently. Node's require(esm) races that in-flight import() and fails
// intermittently with "request for 'module' is not in cache" / "not yet fully
// loaded". Loading it synchronously first leaves nothing in flight to race.
require(require.resolve('@angular/compiler-cli', { paths: [process.cwd()] }));
