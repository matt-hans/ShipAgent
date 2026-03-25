const { withNativeFederation, shareAll } = require('@angular-architects/native-federation/config');

module.exports = withNativeFederation({
  name: 'sidebar-remote',

  exposes: {
    './SidebarContent': './apps/sidebar-remote/src/app/remote-entry.ts',
  },

  shared: {
    ...shareAll({ singleton: true, strictVersion: true, requiredVersion: 'auto' }),
  },

  skip: [
    'rxjs/ajax',
    'rxjs/fetch',
    'rxjs/testing',
    'rxjs/webSocket',
    // @shipagent/testing is a test-only library — must never be bundled as a
    // shared singleton in production federation builds.
    '@shipagent/testing',
    // CSS build tools and Node.js-only packages must be skipped — they cannot
    // be bundled for the browser and do not need to be shared at runtime.
    // Also skip @spartan-ng/brain sub-path exports (e.g. hlm-tailwind-preset)
    // since they reference Node.js packages (tailwindcss-animate).
    'tailwindcss',
    '@tailwindcss/postcss',
    '@spartan-ng/brain',
    '@spartan-ng/brain/hlm-tailwind-preset',
    '@spartan-ng/cli',
    (pkg) => pkg.startsWith('@spartan-ng/brain/'),
  ],

  // ignoreUnusedDeps must be false so the sharedMappings (workspace libs
  // like @shipagent/*) are resolved from tsconfig paths and bundled as
  // singleton shared chunks. When ignoreUnusedDeps is true, removeUnusedDeps()
  // analyses only the standalone app entry (main.ts / NxWelcome) and
  // incorrectly removes all @shipagent/* mappings, causing each remote to
  // bundle its own copy — breaking DI singleton contracts with the shell.
  features: {
    mappingVersion: true,
  },
});
