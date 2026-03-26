import nx from '@nx/eslint-plugin';
import baseConfig from '../../eslint.config.mjs';

export default [
  ...baseConfig,
  ...nx.configs['flat/angular'],
  ...nx.configs['flat/angular-template'],
  {
    files: ['**/*.ts'],
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        {
          type: 'attribute',
          prefix: 'app',
          style: 'camelCase',
        },
      ],
      '@angular-eslint/component-selector': [
        'error',
        {
          type: 'element',
          prefix: 'app',
          style: 'kebab-case',
        },
      ],
      // Allow "on" prefix for output bindings (e.g., onToggle, onConnect).
      '@angular-eslint/no-output-on-prefix': 'warn',
    },
  },
  {
    files: ['**/*.html'],
    rules: {
      // Accessibility: downgrade to warning for overlays/backdrops.
      '@angular-eslint/template/click-events-have-key-events': 'warn',
      '@angular-eslint/template/interactive-supports-focus': 'warn',
      // Allow labels without for= in inline template forms.
      '@angular-eslint/template/label-has-associated-control': 'warn',
    },
  },
];
