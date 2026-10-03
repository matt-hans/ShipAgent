import { runDesktopBoot } from './desktop-handoff';

// Runs from the native `<script type="module">` polyfills bundle, ahead of the
// es-module-shims graph that loads `main`.
void runDesktopBoot();
