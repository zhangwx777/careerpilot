// Diagnostic helper for disposable Windows acceptance runs only.
const path = require("node:path");
const { chromium } = require(path.join(__dirname, "../frontend/node_modules/@playwright/test"));
(async () => {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${Number(process.argv[2])}`, { timeout: 5000 });
  try {
    for (const context of browser.contexts()) {
      for (const page of context.pages()) {
        console.log(JSON.stringify({ url: page.url(), title: await page.title(), startup: await page.locator("body").innerText({ timeout: 5000 }) }));
      }
    }
  } finally { await browser.close(); }
})().catch((error) => { console.log(`Desktop diagnostic unavailable: ${error.message}`); });
