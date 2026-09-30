import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import path from "node:path";

const source = readFileSync(new URL("./main.cjs", import.meta.url), "utf8");
const start = source.indexOf("async function waitFor(");
const end = source.indexOf("function readState", start);

function fixture() {
  let elapsed = 0;
  const service = new EventEmitter();
  service.exitCode = null;
  service.signalCode = null;
  const waitFor = vm.runInNewContext(`(${source.slice(start, end)})`, {
    Date: { now: () => elapsed },
    sleep: async (milliseconds) => { elapsed += milliseconds; },
    Error,
  });
  return { waitFor, service, elapsed: () => elapsed };
}

test("backend becoming ready after 28 seconds still starts", async () => {
  const f = fixture();
  await f.waitFor(async () => f.elapsed() >= 28000, "分析服务", f.service, 120000);
  assert.equal(f.elapsed(), 28000);
});

test("backend exit fails immediately with its stage", async () => {
  const f = fixture();
  f.service.exitCode = 1;
  await assert.rejects(f.waitFor(async () => false, "分析服务", f.service, 120000), /分析服务.*退出.*1/);
  assert.equal(f.elapsed(), 0);
});

test("backend spawn error is reported and listener removed", async () => {
  const f = fixture();
  await assert.rejects(f.waitFor(async () => {
    f.service.emit("error", new Error("ENOENT"));
    return false;
  }, "分析服务", f.service, 120000), /分析服务.*ENOENT/);
  assert.equal(f.service.listenerCount("error"), 0);
});

test("backend never ready times out at the deadline", async () => {
  const f = fixture();
  await assert.rejects(f.waitFor(async () => false, "分析服务", f.service, 120000), /分析服务.*超时/);
  assert.equal(f.elapsed(), 120000);
});

test("ready backend does not wait", async () => {
  const f = fixture();
  await f.waitFor(async () => true, "分析服务", f.service, 120000);
  assert.equal(f.elapsed(), 0);
});

test("loading window is shown before starting local services", async () => {
  const events = [];
  const windowStart = source.indexOf("async function createWindow(");
  const windowEnd = source.indexOf("async function launch", windowStart);
  const context = vm.createContext({
    BrowserWindow: class {
      async loadFile(file) { events.push(["loadFile", file]); }
      show() { events.push(["show"]); }
    },
    path, appRoot: "C:/app", __dirname: "C:/app/resources/app", window: null,
  });
  vm.runInContext(source.slice(windowStart, windowEnd), context);
  await vm.runInContext("createWindow()", context);
  assert.equal(events[0][0], "loadFile");
  assert.match(events[0][1], /startup\.html$/);
  assert.equal(events[1][0], "show");
});

test("startup page is loaded before database and main page after readiness", async () => {
  const events = [];
  const launchStart = source.indexOf("async function launch(");
  const launchEnd = source.indexOf("app.commandLine", launchStart);
  const context = vm.createContext({
    fs: { mkdirSync() {}, writeFileSync() { events.push("state"); } },
    logRoot: "logs", stateFile: "state", dbData: "db", process: { pid: 1 },
    backend: { pid: 2 }, worker: { pid: 3 }, queue: { pid: 4 },
    createWindow: async () => { events.push("loading"); },
    updateStartup: async () => {}, stopPreviousRun() {},
    findFreePort: async () => 50000,
    startPostgres() { events.push("database"); }, startQueue() {}, startWorker() {}, startBackend() {},
    isPostgresReady() {}, isQueueReady() {}, isBackendReady() {},
    waitFor: async (check, stage, service, timeout) => {
      if (stage === "分析服务") { assert.equal(timeout, 120000); events.push("ready"); }
    },
    window: { loadURL: async () => { events.push("main"); } },
  });
  vm.runInContext(source.slice(launchStart, launchEnd), context);
  await vm.runInContext("launch()", context);
  assert.deepEqual(events, ["loading", "database", "ready", "state", "main"]);
});

test("default Electron menu bar is removed", () => {
  assert.match(source, /Menu\.setApplicationMenu\(null\)/);
});

test("installer download reports progress and version is exposed", () => {
  const preload = readFileSync(new URL("./preload.cjs", import.meta.url), "utf8");
  const install = source.slice(source.indexOf('ipcMain.handle("updates:install"'), source.indexOf("function sleep("));
  assert.match(install, /content-length/);
  assert.match(install, /sender\.send\("updates:progress"/);
  assert.match(source, /ipcMain\.handle\("updates:version"/);
  assert.match(preload, /version: \(\) => ipcRenderer\.invoke\("updates:version"\)/);
  assert.match(preload, /onProgress:/);
  assert.match(preload, /removeListener\("updates:progress"/);
});

test("app-only build initializes icon path before using it", () => {
  const build = readFileSync(new URL("../packaging/build.ps1", import.meta.url), "utf8");
  assert.ok(build.indexOf("$iconPath = Join-Path $buildRoot 'brand-mark.ico'") < build.indexOf("if ($AppOnly) {"));
});
