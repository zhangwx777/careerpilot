// Diagnostic helper for disposable Windows acceptance runs only.
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "../frontend/node_modules/@playwright/test"));
async function inspectMain() {
  const endpoint = fs.readFileSync(process.argv[3], "utf8").match(/Debugger listening on (ws:\/\/\S+)/)?.[1];
  if (!endpoint) { console.log("Main inspector endpoint unavailable"); return; }
  const socket = new WebSocket(endpoint);
  const timer = setTimeout(() => { console.log("Main inspector timed out"); socket.close(); }, 8000);
  await new Promise((resolve) => {
    socket.addEventListener("open", () => socket.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: {
      expression: `JSON.stringify({ready:process.mainModule.require('electron').app.isReady(),windows:process.mainModule.require('electron').app.isReady()?process.mainModule.require('electron').BrowserWindow.getAllWindows().map(w=>({url:w.webContents.getURL(),destroyed:w.isDestroyed()})):[],local:process.env.LOCALAPPDATA,resources:process.getActiveResourcesInfo()})`, returnByValue: true,
    } })));
    socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(String(data));
      if (message.id || message.method === "Debugger.paused") console.log(JSON.stringify(message));
      if (message.id === 1) socket.send(JSON.stringify({ id: 2, method: "Debugger.enable" }));
      if (message.id === 2) socket.send(JSON.stringify({ id: 3, method: "Debugger.pause" }));
      if (message.method === "Debugger.paused") { socket.send(JSON.stringify({ id: 4, method: "Debugger.resume" })); socket.close(); }
    });
    socket.addEventListener("close", resolve);
    socket.addEventListener("error", () => { console.log("Main inspector connection failed"); resolve(); });
  });
  clearTimeout(timer);
}
(async () => {
  await inspectMain();
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${Number(process.argv[2])}`, { timeout: 5000 });
  try {
    for (const context of browser.contexts()) {
      for (const page of context.pages()) {
        console.log(JSON.stringify({ url: page.url(), title: await page.title(), startup: await page.locator("body").innerText({ timeout: 5000 }) }));
      }
    }
  } finally { await browser.close(); }
})().catch((error) => { console.log(`Desktop diagnostic unavailable: ${error.message}`); });
