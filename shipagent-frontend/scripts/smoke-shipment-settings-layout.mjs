import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

// Exercise the actual staged production shell/remotes, with only the API boundary
// replaced by synthetic fixtures. No server, credentials or provider calls are used.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(root, 'dist/apps/shell/browser');
const output = process.env.SHIPAGENT_LAYOUT_EVIDENCE_DIR;
const origin = 'http://127.0.0.1:41730';
const report = { screens: [], unexpectedRequests: [], pageErrors: [] };
const settings = {
  onboarding_completed: true, batch_concurrency: 5,
  agent_model: 'claude-haiku-4-5-20251001',
  shipper_name: 'Synthetic International Distribution Warehouse',
  shipper_attention_name: 'Synthetic Shipping Department Contact',
  shipper_phone: '5550100100', shipper_address1: '123 Synthetic Example Street',
  shipper_address2: 'Building 123, Distribution and Logistics Department',
  shipper_city: 'Rancho Santa Margarita', shipper_state: 'CA',
  shipper_zip: '92688-1234', shipper_country: 'US',
};
const fixtures = {
  '/api/v1/auth/session': { required: false, authenticated: true, csrf_token: null },
  '/api/v1/settings': settings,
  '/api/v1/settings/credentials/status': {},
  '/api/v1/platforms/connections': { connections: [] },
  '/api/v1/connections/': [],
  '/api/v1/data-sources/status': { connected: false },
  '/api/v1/saved-sources': { sources: [] },
  '/api/v1/contacts': { contacts: [], total: 0 },
  '/api/v1/commands': { commands: [], total: 0 },
  '/api/v1/conversations/': [],
  '/api/v1/jobs': { jobs: [], total: 0 },
};
const contentTypes = {
  '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json',
  '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};
let rejectSave = false;
let savedAddress;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
  headless: true,
});
try {
  report.browser = await browser.version();
  const context = await browser.newContext({ colorScheme: 'dark' });
  await context.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      report.unexpectedRequests.push(request.url());
      return route.abort();
    }
    if (url.pathname === '/api/v1/settings' && request.method() === 'PATCH') {
      if (rejectSave) return route.fulfill({ status: 422, json: { detail: 'Synthetic validation rejection' } });
      savedAddress = request.postDataJSON();
      Object.assign(settings, savedAddress);
      return route.fulfill({ json: settings });
    }
    if (request.method() === 'GET' && url.pathname in fixtures) {
      return route.fulfill({ json: fixtures[url.pathname] });
    }
    if (url.pathname.startsWith('/api/')) {
      report.unexpectedRequests.push(`${request.method()} ${url.pathname}`);
      return route.fulfill({ status: 501, json: { detail: 'Unexpected fixture request' } });
    }
    const filename = path.resolve(dist, `.${url.pathname === '/' ? '/index.html' : url.pathname}`);
    assert.ok(filename.startsWith(`${dist}${path.sep}`), 'Asset escaped staged production directory');
    try {
      return await route.fulfill({ body: await readFile(filename), contentType: contentTypes[path.extname(filename)] ?? 'application/octet-stream' });
    } catch (error) {
      report.unexpectedRequests.push(url.pathname);
      return route.fulfill({ status: 404, body: String(error) });
    }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', (error) => report.pageErrors.push(error.message));
  const section = page.locator('app-shipment-behaviour-section');
  const scrollArea = page.locator('.settings-flyout-content');

  async function settled() {
    await page.evaluate(async () => {
      await document.fonts.ready;
      for (const animation of document.getAnimations()) {
        if (animation.effect?.getComputedTiming().iterations !== Infinity) animation.finish();
      }
    });
  }

  async function checkBounds(name) {
    await settled();
    const measurements = await section.locator('input, select, button, label, p, .text-destructive').evaluateAll((elements) => elements.map((element) => {
      const r = element.getBoundingClientRect();
      const clippedBy = [];
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.overflowX !== 'visible') {
          const b = parent.getBoundingClientRect();
          if (r.left < b.left - 1 || r.right > b.right + 1) clippedBy.push(parent.className);
        }
      }
      return { name: element.getAttribute('name') ?? element.textContent?.trim(), left: r.left, right: r.right, width: r.width, clippedBy };
    }));
    report.screens.push({ name, viewport: page.viewportSize(), controls: measurements });
    if (output) await page.screenshot({ path: path.join(output, `${name}.png`), animations: 'disabled' });
    for (const control of measurements) {
      assert.ok(control.left >= 0 && control.right <= page.viewportSize().width && control.clippedBy.length === 0,
        `${name}: clipped control ${JSON.stringify(control)}`);
    }
    const widths = await scrollArea.evaluate((element) => ({ scroll: element.scrollWidth, client: element.clientWidth }));
    assert.ok(widths.scroll <= widths.client + 1, `${name}: settings horizontal overflow`);
  }

  for (const viewport of [{ width: 1200, height: 800 }, { width: 900, height: 600 }]) {
    await page.setViewportSize(viewport);
    await page.goto(origin);
    await page.locator('app-rich-chat-input textarea').waitFor({ state: 'visible' });
    await page.getByTitle('Settings', { exact: true }).click();
    await page.getByRole('button', { name: 'Shipment Behaviour', exact: true }).click();
    await page.getByLabel('Agent Model', { exact: true }).waitFor({ state: 'visible' });
    await checkBounds(`initial-${viewport.width}`);
    assert.ok((await section.locator('[name="shipperZip"]').boundingBox()).width >= 140,
      'Postal code must retain a practically editable width');
    // Synthetic translated/expanded label text must wrap rather than widen the row.
    await section.locator('label[for="agent-model-select"]').evaluate((label) => {
      label.textContent = 'Agent model for international shipment preparation and validation';
    });
    await checkBounds(`long-label-${viewport.width}`);

    // The browser uses real local fallbacks; no web-font request is permitted.
    const cdp = await context.newCDPSession(page);
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
    const document = await cdp.send('DOM.getDocument');
    const node = await cdp.send('DOM.querySelector', { nodeId: document.root.nodeId, selector: 'label[for="agent-model-select"]' });
    const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId: node.nodeId });
    assert.ok(fonts.length > 0 && fonts.every((font) => !font.isCustomFont), 'Expected actual local fallback fonts');
    report.screens.at(-1).fonts = fonts;
    await cdp.detach();

    // Tab through the real control sequence, letting focus scroll each field into
    // view. Assert hit-testing as well as bounds so clipped ancestors cannot hide it.
    await page.locator('#agent-model-select').focus();
    for (const name of ['shipperName', 'shipperAttentionName', 'shipperPhone', 'shipperAddress1', 'shipperAddress2', 'shipperCity', 'shipperState', 'shipperZip']) {
      await page.keyboard.press('Tab');
      const input = section.locator(`input[name="${name}"]`);
      assert.equal(await input.evaluate((element) => document.activeElement === element), true, `Tab did not reach ${name}`);
      assert.equal(await input.evaluate((element) => {
        const r = element.getBoundingClientRect();
        return r.top >= 0 && r.bottom <= innerHeight && document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === element;
      }), true, `${name} is not visible and reachable after keyboard focus`);
      assert.equal(await input.evaluate((element) => {
        const style = getComputedStyle(element);
        return element.matches(':focus-visible') && (style.boxShadow !== 'none' ||
          (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0));
      }),
        true, `${name} lost its keyboard focus indicator`);
    }
    await section.locator('[name="shipperCity"]').fill('A deliberately long synthetic municipality name');
    await section.locator('[name="shipperZip"]').fill('12345-6789');
    const postal = section.locator('[name="shipperZip"]');
    await postal.press('Home');
    assert.equal(await postal.evaluate((element) => element.selectionStart), 0);
    await postal.press('End');
    assert.equal(await postal.evaluate((element) => element.selectionStart), 10);
    assert.equal(await postal.evaluate((element) => {
      const style = getComputedStyle(element);
      const canvas = document.createElement('canvas').getContext('2d');
      canvas.font = style.font;
      return canvas.measureText(element.value).width <= element.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    }), true, 'Long postal code should fit without hiding the caret or trailing digits');
    const save = page.getByRole('button', { name: 'Save Shipper Address', exact: true });
    await page.keyboard.press('Tab');
    assert.equal(await save.evaluate((element) => document.activeElement === element), true);
    await checkBounds(`edited-${viewport.width}`);
    rejectSave = true;
    await save.press('Enter');
    await section.getByText('Failed to save shipper address.', { exact: true }).waitFor({ state: 'visible' });
    await checkBounds(`validation-${viewport.width}`);
    await section.getByText('Failed to save shipper address.', { exact: true }).evaluate((message) => {
      message.textContent = 'The synthetic shipping address could not be validated. Review the postal code and municipality, then retry saving the complete address.';
    });
    await checkBounds(`long-validation-${viewport.width}`);
    assert.equal(await section.locator('[name="shipperZip"]').inputValue(), '12345-6789');
    rejectSave = false;
    await save.click();
    await save.waitFor({ state: 'detached' });
    assert.equal(savedAddress.shipper_zip, '12345-6789');
    assert.equal(savedAddress.shipper_city, 'A deliberately long synthetic municipality name');
    await scrollArea.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await checkBounds(`scrolled-${viewport.width}`);
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    await page.locator('app-settings-flyout').waitFor({ state: 'detached' });
    await page.getByTitle('Settings', { exact: true }).click();
    await page.getByRole('button', { name: 'Shipment Behaviour', exact: true }).click();
    await checkBounds(`reopened-${viewport.width}`);
    assert.equal(await section.locator('[name="shipperZip"]').inputValue(), '12345-6789');
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  }
  assert.deepEqual(report.unexpectedRequests, []);
  assert.deepEqual(report.pageErrors, []);
  report.passed = true;
  console.log('SHIPMENT_SETTINGS_LAYOUT_OK: 1200x800 and 900x600, local fonts, keyboard, validation/retry and reopen');
} finally {
  await browser.close();
  if (output) await writeFile(path.join(output, 'layout.json'), `${JSON.stringify(report, null, 2)}\n`);
}
