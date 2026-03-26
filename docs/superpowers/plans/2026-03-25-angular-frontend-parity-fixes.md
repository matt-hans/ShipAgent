# Angular Frontend Parity Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Angular Module Federation frontend to pixel-perfect visual and functional parity with the React frontend.

**Architecture:** The root cause of most visual gaps is that Tailwind CSS v4 only scans source files referenced by `@source` directives. The shell's `styles.css` only scans its own templates and shared libs — NOT remote app templates. This means all Tailwind utility classes used in chat-remote, sidebar-remote, settings-remote, and domain-remote components are MISSING from the compiled CSS. Fix this, then address remaining layout/structural gaps.

**Tech Stack:** Angular 21, Native Federation, Tailwind CSS v4, NgRx SignalStore, Nx

**Working Directory:** `/Users/matthewhans/Desktop/Programming/ShipAgent-Phase9`

---

## Task 1: Fix Tailwind CSS Source Scanning for All Remotes

**The meta-fix.** This single change resolves the majority of visual issues (vertical steps, missing borders, broken layouts) because Tailwind utility classes from remote templates are not being compiled.

**Files:**
- Modify: `shipagent-frontend/apps/shell/src/styles.css` (line 2-3)

- [ ] **Step 1: Add `@source` directives for all remote apps**

```css
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:ital,wght@0,100..800;1,100..800&display=swap');
@import 'tailwindcss' source('./app');
@source "../../../libs/shared/ui/src";
@source "../../../libs/shared/state/src";
@source "../../../libs/shared/sse/src";
@source "../../chat-remote/src";
@source "../../sidebar-remote/src";
@source "../../settings-remote/src";
@source "../../domain-remote/src";
```

The `@source` directive tells Tailwind v4 to scan these directories for utility class usage. Without this, classes like `grid-cols-3`, `max-w-lg`, `line-clamp-2`, `badge-success`, etc. used in remote templates are never compiled into the CSS output.

- [ ] **Step 2: Rebuild production and verify CSS size increase**

```bash
cd shipagent-frontend && rm -rf .angular/cache && npx nx build shell --configuration=production 2>&1 | grep -E "styles|Initial total"
```

Expected: `styles.css` should increase from ~56 kB to ~60-70 kB (more utility classes compiled). If it stays the same, the @source paths are wrong.

- [ ] **Step 3: Verify grid-cols-3 is now in compiled CSS**

```bash
grep "grid-cols-3\|grid-template-columns.*3" shipagent-frontend/dist/apps/shell/browser/styles-*.css && echo "FOUND" || echo "MISSING — check @source paths"
```

- [ ] **Step 4: Commit**

```bash
git add shipagent-frontend/apps/shell/src/styles.css
git commit -m "fix(09): add @source directives for all remotes — fixes Tailwind class compilation"
```

---

## Task 2: Add Right-Side Action Icons to Chat Container

**The React CommandCenter has a right-side vertical icon panel with +, gear, and clock buttons. Angular is missing this entirely.**

**Files:**
- Modify: `shipagent-frontend/apps/chat-remote/src/app/chat-container/chat-container.component.ts`

**Reference:** React `frontend/src/components/CommandCenter.tsx:896-920`

- [ ] **Step 1: Update the chat container template to add right-side icons**

The template currently has:
```html
<div class="flex flex-col h-full bg-background overflow-hidden">
  <!-- banners -->
  <app-message-list ... />
  <!-- tool chip -->
  <!-- input area -->
</div>
```

Change the message list + icons section to wrap in a flex row (matching React's structure):

```html
<div class="flex flex-col h-full bg-background overflow-hidden">
  <!-- banners (same as before) -->
  @if (conversationStore.interactiveShipping()) {
    <app-interactive-mode-banner />
  } @else if (dataSourceStore.activeSourceType()) {
    <app-active-source-banner />
  }

  <!-- Message area + right icon panel -->
  <div class="flex flex-1 overflow-hidden">
    <app-message-list
      #messageList
      class="flex-1 overflow-hidden flex flex-col"
      [interactiveShipping]="conversationStore.interactiveShipping()"
      (exampleClick)="handleExampleClick($event)"
    />

    <!-- Right edge: action icons -->
    <div class="flex flex-col items-center pt-3 pr-1 gap-2">
      <button
        (click)="handleNewChat()"
        [disabled]="conversationStore.isStreaming()"
        class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
        title="New chat"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </button>
      <button
        (click)="openSettings()"
        class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
        title="Settings"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
        </svg>
      </button>
      <button
        class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
        title="Chat history"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        </svg>
      </button>
    </div>
  </div>

  <!-- tool chip + input area (same as before) -->
</div>
```

- [ ] **Step 2: Add handler methods to the component class**

```typescript
private readonly appStore = inject(AppStore);

handleNewChat(): void {
  this.chatActions.startNewChat();
}

openSettings(): void {
  this.appStore.openSettings();
}
```

Add import: `import { AppStore } from '@shipagent/shared-state';`

- [ ] **Step 3: Rebuild and verify icons appear**

```bash
cd shipagent-frontend && npx nx build shell --configuration=production
```

- [ ] **Step 4: Commit**

```bash
git add shipagent-frontend/apps/chat-remote/src/app/chat-container/chat-container.component.ts
git commit -m "feat(09): add right-side action icons to chat container (new chat, settings, history)"
```

---

## Task 3: Fix Input Area — Rich Placeholder and Send Icon

**React has context-aware placeholder text and a paper-plane send icon. Angular has plain "Enter a command..." with "Send" text.**

**Files:**
- Modify: `shipagent-frontend/apps/chat-remote/src/app/chat-container/chat-container.component.ts`

**Reference:** React `frontend/src/components/CommandCenter.tsx:924-960`

- [ ] **Step 1: Add computed placeholder and update input area**

Add a computed signal for the placeholder:
```typescript
protected readonly inputPlaceholder = computed(() => {
  if (this.conversationStore.interactiveShipping()) {
    return 'Describe one shipment from scratch...';
  }
  if (!this.dataSourceStore.activeSourceType()) {
    return 'Track a package, find locations, or connect a data source...';
  }
  return 'Enter a shipping command...';
});
```

Update the textarea placeholder binding:
```html
[placeholder]="inputPlaceholder()"
```

Replace the "Send" text button with an SVG icon:
```html
<button
  class="btn-primary p-2.5 flex-shrink-0 rounded-lg"
  [disabled]="!inputValue().trim() || conversationStore.isStreaming()"
  (click)="handleSubmit()"
>
  @if (conversationStore.isStreaming()) {
    <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M7.76 7.76L4.93 4.93" />
    </svg>
  } @else {
    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  }
</button>
```

- [ ] **Step 2: Add max-w-3xl constraint and backdrop blur to input area**

Update the input wrapper to match React:
```html
<div class="border-t border-slate-800 px-4 py-3 bg-card/30 backdrop-blur">
  <div class="max-w-3xl mx-auto">
    <div class="flex items-end gap-2">
      <!-- textarea + button -->
    </div>
    <p class="text-[10px] font-mono text-slate-500 mt-1.5">
      Use /commands and &#64;contacts for shortcuts · Press Enter to send
    </p>
  </div>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add shipagent-frontend/apps/chat-remote/src/app/chat-container/chat-container.component.ts
git commit -m "fix(09): rich placeholder, send icon, max-width constraint, help text in chat input"
```

---

## Task 4: Fix Sidebar Default Tab — Show Data Tab Content by Default

**The sidebar shows "Data" tab as active but no content renders underneath. The Data tab should show the full DataSourcePanel (platform cards, import buttons, etc.).**

**Files:**
- Modify: `shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/data-source-panel.component.ts` (if needed)
- Modify: `shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/platform-source.component.ts` (if needed)

The sidebar content component code looks correct — it renders `<sa-data-source-panel />` when `activeTab() === 'data'`. The issue is likely:
1. The NG0200/NG0201 DI errors preventing the panel from initializing
2. Or the panel renders but with missing CSS classes (fixed by Task 1)

- [ ] **Step 1: Check for DI errors in the platform source component**

Read the full PlatformSourceComponent and DataSourcePanelComponent to check if they inject services that require specific providers not available in the remote's DI context. Common issue: injecting `PlatformsStore` or `ApiService` without proper provider configuration.

```bash
cd shipagent-frontend && npx nx build sidebar-remote --configuration=production 2>&1 | tail -20
```

- [ ] **Step 2: Verify the sidebar remote's entry providers are correct**

Read `apps/sidebar-remote/src/app/remote-entry.ts` — ensure all needed services are listed in providers.

- [ ] **Step 3: After Task 1 CSS fix, rebuild and check if sidebar content now renders**

```bash
cd shipagent-frontend && npx nx build shell --configuration=production
```

Symlink remotes into shell dist (same as before):
```bash
cd dist/apps/shell/browser
for remote in chat-remote sidebar-remote settings-remote domain-remote; do
  ln -sfn "../../$remote/browser" "$remote"
done
```

Restart backend and verify sidebar renders data source panel content.

- [ ] **Step 4: If content still missing, add `scrollable` class to sidebar panel overflow area**

The shell styles define `.scrollable` for custom scrollbar styling. The sidebar panel content div may need this class:
```html
<div class="flex-1 overflow-y-auto scrollable">
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -A shipagent-frontend/apps/sidebar-remote/
git commit -m "fix(09): resolve sidebar panel rendering and DI issues"
```

---

## Task 5: Symlink Automation — Post-Build Script

**Currently, remotes must be manually symlinked into the shell dist after every build. Add a script to automate this.**

**Files:**
- Create: `shipagent-frontend/scripts/link-remotes.sh`

- [ ] **Step 1: Create the link script**

```bash
#!/usr/bin/env bash
# Link remote build outputs into shell dist for unified serving
set -e
DIST="$(dirname "$0")/../dist/apps/shell/browser"

if [ ! -d "$DIST" ]; then
  echo "Shell dist not found at $DIST — run 'nx build shell' first"
  exit 1
fi

for remote in chat-remote sidebar-remote settings-remote domain-remote; do
  ln -sfn "../../$remote/browser" "$DIST/$remote"
  echo "Linked $remote"
done

echo "All remotes linked. Serve from: $DIST"
```

```bash
chmod +x shipagent-frontend/scripts/link-remotes.sh
```

- [ ] **Step 2: Commit**

```bash
git add shipagent-frontend/scripts/link-remotes.sh
git commit -m "feat(09): add post-build remote linking script"
```

---

## Task 6: Production Build + End-to-End Verification

- [ ] **Step 1: Full production build**

```bash
cd shipagent-frontend
rm -rf .angular/cache dist/
npx nx build shell --configuration=production
./scripts/link-remotes.sh
```

- [ ] **Step 2: Restart backend and verify**

```bash
# Kill old backend
lsof -ti:8000 | xargs kill -9

# Start from worktree with venv
cd /Users/matthewhans/Desktop/Programming/ShipAgent-Phase9
ALLOWED_ORIGINS=http://localhost:4200 /Users/matthewhans/Desktop/Programming/ShipAgent/.venv/bin/python -m uvicorn src.api.main:app --port 8000
```

- [ ] **Step 3: Mark onboarding complete and verify full UI**

```bash
curl -s -X POST http://localhost:8000/api/v1/settings/onboarding/complete
```

Open http://localhost:8000 and verify:
- [ ] Header: ShipAgent logo + Single Shipment toggle
- [ ] Sidebar Data tab: Platform cards (Shopify/Amazon if configured), Import File/Database buttons, Saved Sources
- [ ] Sidebar Jobs tab: Shipment History with search + filters
- [ ] Sidebar Chats tab: Chat sessions grouped by date
- [ ] Chat area: Welcome message with horizontal 3-step layout (1-Connect, 2-Describe, 3-Ship)
- [ ] Example commands in styled cards
- [ ] Right-side icons: +, gear, clock
- [ ] Input: Context-aware placeholder, send icon, help text
- [ ] Full height layout — no empty space below input

- [ ] **Step 4: Commit all remaining fixes**

```bash
git add -A
git commit -m "fix(09): angular frontend parity — CSS source scanning, layout fixes, right-side icons"
```

---

## Summary of Root Causes

| Gap | Root Cause | Fix |
|-----|-----------|-----|
| Steps vertical instead of horizontal | `grid-cols-3` not in compiled CSS | Task 1: Add `@source` for remote dirs |
| Sidebar panels empty | Missing CSS + possible DI errors | Task 1 + Task 4 |
| No right-side action icons | Not implemented in Angular chat container | Task 2 |
| Plain input placeholder | Hardcoded "Enter a command..." | Task 3 |
| Send text instead of icon | Not ported from React | Task 3 |
| No max-width constraint on input | Missing `max-w-3xl mx-auto` wrapper | Task 3 |
| No help text below input | Not ported from React | Task 3 |
| Manual symlink after build | No automation | Task 5 |
