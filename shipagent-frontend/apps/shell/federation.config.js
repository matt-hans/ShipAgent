const { withNativeFederation, shareAll } = require('@angular-architects/native-federation/config');

module.exports = withNativeFederation({
  name: 'shell',

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

  features: {
    // Required for Nx mapped paths to work correctly
    mappingVersion: true,
    // Skip unused deps for better build performance
    ignoreUnusedDeps: true,
  },
});
