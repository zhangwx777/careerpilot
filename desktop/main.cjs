const { app, BrowserWindow, Menu, dialog, ipcMain, net: electronNet, session } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const { Readable } = require("node:stream");
const { pipeline } = require("node:stream/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const appRoot = path.dirname(process.execPath);
const appLayer = path.join(appRoot, "app");
const runtimeRoot = path.join(appRoot, "runtime");
const dataRoot = path.join(process.env.LOCALAPPDATA, "CareerPilot");
const dbData = path.join(dataRoot, "postgres");
const queueData = path.join(dataRoot, "queue");
const logRoot = path.join(dataRoot, "logs");
const stateFile = path.join(dataRoot, "runtime.json");
const updateConfigPath = path.join(__dirname, "update-config.json");
const pgBin = path.join(runtimeRoot, "postgresql", "bin");
const pgCtl = path.join(pgBin, "pg_ctl.exe");
const pgIsReady = path.join(pgBin, "pg_isready.exe");
const initdb = path.join(pgBin, "initdb.exe");
const backendExe = path.join(runtimeRoot, "backend", "CareerPilotBackend.exe");
const garnetExe = path.join(runtimeRoot, "garnet", "GarnetServer.exe");
const dotnetRoot = path.join(runtimeRoot, "dotnet");
const releaseApiUrl = "https://api.github.com/repos/zhangwx777/careerpilot/releases/latest";
const installerAssetName = "CareerPilotSetup.exe";
const maxDownloadAttempts = 3;
const downloadIdleTimeoutMilliseconds = 60_000;

let backend;
let worker;
let queue;
let window;
let dbPort;
let backendPort;
let queuePort;
let shuttingDown = false;

function run(executable, args) {
  return spawnSync(executable, args, { stdio: "ignore", windowsHide: true });
}

function compareVersions(left, right) {
  const parts = (version) => version.replace(/^v/, "").split(".").map(Number);
  const a = parts(left);
  const b = parts(right);
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return 0;
}

function readUpdateConfig() {
  try {
    const config = JSON.parse(fs.readFileSync(updateConfigPath, "utf8"));
    return config && typeof config === "object" ? config : {};
  } catch (error) {
    if (error.code !== "ENOENT") console.warn("CareerPilot 更新镜像配置无法读取。", error.message);
    return {};
  }
}

function configuredHttpsUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    if (url.protocol === "https:" && !url.username && !url.password) return url.href;
  } catch { /* 无效的配置地址 */ }
  return null;
}

function updateManifestUrl() {
  const config = readUpdateConfig();
  const value = process.env.CAREERPILOT_UPDATE_MANIFEST_URL || config.manifestUrl;
  const url = configuredHttpsUrl(value);
  if (value && !url) console.warn("CareerPilot 更新清单必须使用不含凭据的 HTTPS 地址。");
  return url;
}

function parseRelease(release) {
  if (!release || typeof release !== "object") throw new Error("更新信息格式无效。");
  const version = String(release.tag_name ?? "").replace(/^v/, "");
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error("更新信息中的版本标签格式无效。");
  const asset = (Array.isArray(release.assets) ? release.assets : []).find((item) => item.name === installerAssetName);
  const digest = /^sha256:([a-f\d]{64})$/i.exec(String(asset?.digest ?? ""))?.[1]?.toLowerCase() ?? null;
  let downloadUrl = null;
  if (asset?.browser_download_url) {
    try {
      const parsedUrl = new URL(asset.browser_download_url);
      if (parsedUrl.protocol === "https:" && parsedUrl.hostname === "github.com") downloadUrl = parsedUrl.href;
    } catch { /* 忽略无效下载地址 */ }
  }
  return {
    version,
    installer: asset ? {
      url: downloadUrl,
      size: Number.isSafeInteger(Number(asset.size)) ? Number(asset.size) : 0,
      sha256: digest,
    } : null,
  };
}

async function releaseFromUrl(url, sourceName) {
  let response;
  try {
    response = await electronNet.fetch(url, {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "CareerPilot" },
      signal: AbortSignal.timeout(15_000),
      cache: "no-store",
    });
  } catch {
    throw new Error(`${sourceName}连接失败或超时。`);
  }
  if (new URL(response.url).protocol !== "https:") throw new Error("更新信息源跳转到了不安全的 HTTP 地址。");
  if (!response.ok) throw new Error(`${sourceName}请求失败（${response.status}）。`);
  try {
    return parseRelease(await response.json());
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error(`${sourceName}返回的更新信息不是有效 JSON。`);
    throw error;
  }
}

async function latestRelease() {
  const sources = [{ url: releaseApiUrl, name: "GitHub Releases" }];
  const manifestUrl = updateManifestUrl();
  if (manifestUrl) sources.push({ url: manifestUrl, name: "更新镜像" });
  const failures = [];
  for (const source of sources) {
    try {
      const release = await releaseFromUrl(source.url, source.name);
      if (release.installer?.url && release.installer.size > 0) return release;
      failures.push(`${source.name}中没有有效的安装包信息。`);
    } catch (error) {
      failures.push(error.message);
    }
  }
  throw new Error(`无法获取更新信息。${failures.join("；")}`);
}

function updateMirrorUrl(version) {
  const config = readUpdateConfig();
  const template = process.env.CAREERPILOT_UPDATE_MIRROR_URL_TEMPLATE || config.mirrorUrlTemplate;
  if (typeof template !== "string" || !template.trim()) return null;
  if (!template.includes("{version}")) {
    console.warn("CareerPilot 更新镜像模板缺少 {version}，改用 GitHub。");
    return null;
  }
  try {
    const url = new URL(template.trim().replaceAll("{version}", encodeURIComponent(version)));
    if (url.protocol !== "https:" || url.username || url.password) {
      console.warn("CareerPilot 更新镜像必须使用不含凭据的 HTTPS 地址，改用 GitHub。");
      return null;
    }
    return url.href;
  } catch {
    console.warn("CareerPilot 更新镜像地址无效，改用 GitHub。");
    return null;
  }
}

class UpdateDownloadError extends Error {
  constructor(message, { retryable = true } = {}) {
    super(message);
    this.retryable = retryable;
  }
}

function updateProgress(event, receivedBytes, totalBytes, startedAt, source, transferredBytes = 0) {
  const elapsedSeconds = Math.max((Date.now() - startedAt) / 1000, 0.001);
  const percent = totalBytes > 0 ? Math.min(99, Math.floor((receivedBytes / totalBytes) * 100)) : null;
  event.sender.send("updates:progress", {
    percent,
    receivedBytes,
    totalBytes,
    bytesPerSecond: Math.round(transferredBytes / elapsedSeconds),
    source,
  });
}

async function installerMatches(pathname, size, sha256) {
  try {
    const stat = await fs.promises.stat(pathname);
    if (size > 0 && stat.size !== size) return false;
    if (!sha256) return true;
    const hash = crypto.createHash("sha256");
    await new Promise((resolve, reject) => {
      const file = fs.createReadStream(pathname);
      file.on("data", (chunk) => hash.update(chunk));
      file.once("error", reject);
      file.once("end", () => resolve());
    });
    return hash.digest("hex") === sha256;
  } catch {
    return false;
  }
}

function parseContentRange(value) {
  const match = /^bytes\s+(\d+)-(\d+)\/(\d+|\*)$/i.exec(value ?? "");
  if (!match) return null;
  return { start: Number(match[1]), end: Number(match[2]), total: match[3] === "*" ? 0 : Number(match[3]) };
}

async function downloadFromSource(source, partialPath, installer, event, startedAt, transferStats) {
  let lastError;
  for (let attempt = 0; attempt < maxDownloadAttempts; attempt += 1) {
    let receivedBytes = 0;
    try {
      receivedBytes = (await fs.promises.stat(partialPath)).size;
    } catch { /* 首次下载 */ }

    if (installer.size > 0 && receivedBytes > installer.size) {
      await fs.promises.rm(partialPath, { force: true });
      receivedBytes = 0;
    }
    if (installer.size > 0 && receivedBytes === installer.size) {
      if (await installerMatches(partialPath, installer.size, installer.sha256)) return;
      await fs.promises.rm(partialPath, { force: true });
      receivedBytes = 0;
    }

    const controller = new AbortController();
    let idleTimer;
    const resetIdleTimer = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => controller.abort(), downloadIdleTimeoutMilliseconds);
    };
    let lastReportedPercent = null;
    let lastReportedAt = 0;
    const reportProgress = () => {
      const percent = installer.size > 0 ? Math.min(99, Math.floor((receivedBytes / installer.size) * 100)) : null;
      const now = Date.now();
      if (percent !== lastReportedPercent || now - lastReportedAt >= 1000) {
        updateProgress(event, receivedBytes, installer.size, startedAt, source.name, transferStats.bytes);
        lastReportedPercent = percent;
        lastReportedAt = now;
      }
    };
    resetIdleTimer();
    try {
      const headers = receivedBytes > 0 ? { Range: `bytes=${receivedBytes}-` } : {};
      const response = await electronNet.fetch(source.url, { headers, signal: controller.signal, cache: "no-store" });
      if (new URL(response.url).protocol !== "https:") {
        throw new UpdateDownloadError("下载源跳转到了不安全的 HTTP 地址。", { retryable: false });
      }

      if (response.status === 416) {
        if (installer.size > 0 && receivedBytes === installer.size
            && await installerMatches(partialPath, installer.size, installer.sha256)) return;
        await fs.promises.rm(partialPath, { force: true });
        throw new UpdateDownloadError("下载源的续传位置已失效，将重新下载。");
      }
      if (!response.ok) {
        const retryable = response.status === 408 || response.status === 429 || response.status >= 500;
        throw new UpdateDownloadError(`下载源返回 HTTP ${response.status}。`, { retryable });
      }

      if (receivedBytes > 0 && response.status === 200) {
        await fs.promises.rm(partialPath, { force: true });
        receivedBytes = 0;
      } else if (response.status === 206) {
        const range = parseContentRange(response.headers.get("content-range"));
        if (!range || range.start !== receivedBytes || (installer.size > 0 && range.total > 0 && range.total !== installer.size)) {
          await fs.promises.rm(partialPath, { force: true });
          throw new UpdateDownloadError("下载源返回了不匹配的分段数据。");
        }
      } else if (response.status !== 200) {
        throw new UpdateDownloadError(`下载源返回 HTTP ${response.status}。`, { retryable: response.status >= 500 });
      }
      if (!response.body) throw new UpdateDownloadError("下载源没有返回文件内容。");

      reportProgress();
      const body = Readable.fromWeb(response.body);
      body.on("data", (chunk) => {
        receivedBytes += chunk.length;
        transferStats.bytes += chunk.length;
        resetIdleTimer();
        reportProgress();
      });
      await pipeline(body, fs.createWriteStream(partialPath, { flags: receivedBytes > 0 ? "a" : "w" }));

      const stat = await fs.promises.stat(partialPath);
      if (installer.size > 0 && stat.size > installer.size) {
        await fs.promises.rm(partialPath, { force: true });
        throw new UpdateDownloadError("下载文件大小与发行信息不符。", { retryable: false });
      }
      if (installer.size > 0 && stat.size < installer.size) {
        throw new UpdateDownloadError("下载中断，正在尝试续传。");
      }
      if (installer.sha256 && !(await installerMatches(partialPath, installer.size, installer.sha256))) {
        await fs.promises.rm(partialPath, { force: true });
        throw new UpdateDownloadError("安装包 SHA-256 校验失败。", { retryable: false });
      }
      return;
    } catch (error) {
      lastError = error instanceof UpdateDownloadError
        ? error
        : new UpdateDownloadError("网络连接中断或等待数据超时。");
      if (!lastError.retryable || attempt === maxDownloadAttempts - 1) {
        throw new UpdateDownloadError(lastError.message, { retryable: false });
      }
      await sleep(1000 * (attempt + 1));
    } finally {
      clearTimeout(idleTimer);
    }
  }
  throw lastError ?? new UpdateDownloadError("下载失败。");
}

async function downloadInstaller(release, event, installerPath) {
  const installer = release.installer;
  const partialPath = `${installerPath}.part`;
  const sources = [];
  const mirrorUrl = installer.sha256 ? updateMirrorUrl(release.version) : null;
  if (mirrorUrl && mirrorUrl !== installer.url) sources.push({ name: "mirror", url: mirrorUrl });
  sources.push({ name: "github", url: installer.url });

  const startedAt = Date.now();
  const transferStats = { bytes: 0 };
  const existingSize = (await fs.promises.stat(partialPath).catch(() => null))?.size ?? 0;
  updateProgress(event, existingSize, installer.size, startedAt, sources[0].name, transferStats.bytes);
  const failures = [];
  for (const source of sources) {
    try {
      await downloadFromSource(source, partialPath, installer, event, startedAt, transferStats);
      await fs.promises.rm(installerPath, { force: true });
      await fs.promises.rename(partialPath, installerPath);
      event.sender.send("updates:progress", {
        percent: 100,
        receivedBytes: installer.size,
        totalBytes: installer.size,
        bytesPerSecond: Math.round(transferStats.bytes / Math.max((Date.now() - startedAt) / 1000, 0.001)),
        source: source.name,
      });
      return;
    } catch (error) {
      failures.push(`${source.name === "mirror" ? "镜像" : "GitHub"}：${error.message}`);
      console.warn(`CareerPilot 更新下载失败（${source.name}）：${error.message}`);
    }
  }
  throw new Error(`安装包下载失败。${failures.join("；")} 请检查网络后重试。`);
}

ipcMain.handle("updates:version", () => app.getVersion());

ipcMain.handle("updates:check", async () => {
  const release = await latestRelease();
  const currentVersion = app.getVersion();
  return {
    currentVersion,
    latestVersion: release.version,
    updateAvailable: compareVersions(release.version, currentVersion) > 0,
    installerAvailable: Boolean(release.installer?.url),
  };
});

ipcMain.handle("updates:install", async (event) => {
  const release = await latestRelease();
  if (compareVersions(release.version, app.getVersion()) <= 0) throw new Error("当前已是最新版本。");
  if (!release.installer?.url) throw new Error("最新 Release 中没有有效的 CareerPilotSetup.exe 下载地址。");
  const installerPath = path.join(app.getPath("temp"), `CareerPilotSetup-${release.version}.exe`);
  if (!release.installer.size) throw new Error("Release 中缺少有效的安装包大小，无法安全下载。");
  await downloadInstaller(release, event, installerPath);

  await new Promise((resolve, reject) => {
    const installer = spawn(installerPath, [], { detached: true, stdio: "ignore", windowsHide: true });
    installer.once("error", reject);
    installer.once("spawn", () => {
      installer.unref();
      resolve();
    });
  });
  app.quit();
});

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const listener = net.createServer();
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", () => {
      const address = listener.address();
      if (!address || typeof address === "string") {
        listener.close(() => reject(new Error("无法读取系统分配的端口。")));
        return;
      }
      listener.close(() => resolve(address.port));
    });
  });
}

function isPostgresReady(port) {
  return run(pgIsReady, ["-h", "127.0.0.1", "-p", String(port)]).status === 0;
}

function isQueueReady(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    const finish = (ready) => { socket.destroy(); resolve(ready); };
    socket.setTimeout(1000, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}

function isBackendReady(port) {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/health`, { timeout: 2000 }, (response) => {
      let body = "";
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        try {
          const health = JSON.parse(body);
          resolve(response.statusCode === 200 && health.status === "ok" && health.db === true);
        } catch {
          resolve(false);
        }
      });
    });
    request.on("error", () => resolve(false));
    request.on("timeout", () => request.destroy());
  });
}

async function waitFor(check, stage, service, timeoutMilliseconds = 20000) {
  const deadline = Date.now() + timeoutMilliseconds;
  let startError;
  const onError = (error) => { startError = error; };
  service?.once("error", onError);
  try {
    while (Date.now() < deadline) {
      if (startError) throw new Error(`${stage}无法启动：${startError.message}`);
      if (service && (service.exitCode !== null || service.signalCode !== null)) {
        throw new Error(`${stage}提前退出（${service.exitCode ?? service.signalCode}）。`);
      }
      const ready = await check();
      if (startError) throw new Error(`${stage}无法启动：${startError.message}`);
      if (ready) return;
      await sleep(500);
    }
    throw new Error(`${stage}启动超时，请查看启动日志。`);
  } finally {
    service?.removeListener("error", onError);
  }
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(stateFile, "utf8"));
  } catch {
    return null;
  }
}

function stopPreviousRun() {
  const previous = readState();
  if (previous?.backend_pid) run("taskkill.exe", ["/PID", String(previous.backend_pid), "/T", "/F"]);
  if (previous?.worker_pid) run("taskkill.exe", ["/PID", String(previous.worker_pid), "/T", "/F"]);
  if (previous?.queue_pid) run("taskkill.exe", ["/PID", String(previous.queue_pid), "/T", "/F"]);
  if (fs.existsSync(path.join(dbData, "PG_VERSION"))) run(pgCtl, ["-D", dbData, "stop", "-m", "fast"]);
  fs.rmSync(stateFile, { force: true });
}

function startPostgres() {
  fs.mkdirSync(dbData, { recursive: true });
  if (!fs.existsSync(path.join(dbData, "PG_VERSION"))) {
    const result = run(initdb, ["-D", dbData, "-L", path.join(runtimeRoot, "postgresql", "share"), "-U", "qiuzhao_app", "-A", "trust", "--encoding=UTF8", "--no-locale"]);
    if (result.status !== 0) throw new Error("本地数据库初始化失败，请重新安装。 ");
  }
  spawn(pgCtl, ["-D", dbData, "-l", path.join(logRoot, "postgres.log"), "-o", `-h 127.0.0.1 -p ${dbPort}`, "start"], { detached: false, stdio: "ignore", windowsHide: true });
}

function startBackend() {
  const output = fs.openSync(path.join(logRoot, "backend.log"), "a");
  const errors = fs.openSync(path.join(logRoot, "backend-error.log"), "a");
  backend = spawn(backendExe, [], {
    cwd: appLayer,
    env: serviceEnv(),
    stdio: ["ignore", output, errors],
    windowsHide: true,
  });
}

function startWorker() {
  const output = fs.openSync(path.join(logRoot, "worker.log"), "a");
  const errors = fs.openSync(path.join(logRoot, "worker-error.log"), "a");
  worker = spawn(backendExe, [], {
    cwd: appLayer,
    env: serviceEnv({ CAREERPILOT_WORKER: "1" }),
    stdio: ["ignore", output, errors],
    windowsHide: true,
  });
}

function startQueue() {
  fs.mkdirSync(queueData, { recursive: true });
  const output = fs.openSync(path.join(logRoot, "queue.log"), "a");
  const errors = fs.openSync(path.join(logRoot, "queue-error.log"), "a");
  queue = spawn(garnetExe, [
    "--bind", "127.0.0.1",
    "--port", String(queuePort),
    "--memory", "256m",
    "--index", "16m",
    "--lua",
  ], {
    cwd: queueData,
    env: { ...process.env, DOTNET_ROOT_X64: dotnetRoot, DOTNET_ROOT: dotnetRoot },
    stdio: ["ignore", output, errors],
    windowsHide: true,
  });
}

function serviceEnv(extra = {}) {
  const queueUrl = `redis://127.0.0.1:${queuePort}/0`;
  return {
    ...process.env,
    DATABASE_URL: `postgresql+psycopg://qiuzhao_app@127.0.0.1:${dbPort}/postgres`,
    TEST_DATABASE_URL: "",
    CAREERPILOT_APP_ROOT: appLayer,
    CAREERPILOT_DATA_DIR: dataRoot,
    CAREERPILOT_BACKEND_PORT: String(backendPort),
    CELERY_BROKER_URL: queueUrl,
    CELERY_RESULT_BACKEND: queueUrl,
    ...extra,
  };
}

async function stopPostgres() {
  if (fs.existsSync(path.join(dbData, "PG_VERSION"))) run(pgCtl, ["-D", dbData, "stop", "-m", "fast"]);
}

async function shutdown(event) {
  if (shuttingDown) return;
  shuttingDown = true;
  event?.preventDefault();
  if (backend && !backend.killed) backend.kill();
  if (worker && !worker.killed) worker.kill();
  if (queue && !queue.killed) queue.kill();
  await stopPostgres();
  fs.rmSync(stateFile, { force: true });
  app.exit();
}

async function createWindow() {
  window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    show: false,
    icon: path.join(appRoot, "brand-mark.png"),
    webPreferences: { contextIsolation: true, preload: path.join(__dirname, "preload.cjs"), zoomFactor: 0.9 },
  });
  await window.loadFile(path.join(__dirname, "startup.html"));
  window.show();
}

async function updateStartup(stage, detail, step, failed = false) {
  await window.webContents.executeJavaScript(`
    document.getElementById("startup-stage").textContent = ${JSON.stringify(stage)};
    document.getElementById("startup-detail").textContent = ${JSON.stringify(detail)};
    document.body.dataset.failed = ${JSON.stringify(String(failed))};
    document.querySelectorAll(".steps li").forEach((item, index) => {
      item.className = index < ${step} ? "done" : index === ${step} ? "active" : "";
    });
  `);
}

async function launch() {
  fs.mkdirSync(logRoot, { recursive: true });
  await createWindow();
  await updateStartup("正在准备本地资料", "首次启动可能需要稍久，请保持窗口打开。", 0);
  stopPreviousRun();
  dbPort = await findFreePort(55432);
  startPostgres();
  await waitFor(() => isPostgresReady(dbPort), "本地数据库");
  await updateStartup("正在准备分析环境", "正在连接本地任务服务。", 1);
  queuePort = await findFreePort(6379);
  startQueue();
  await waitFor(() => isQueueReady(queuePort), "任务服务", queue);
  backendPort = await findFreePort(58080);
  await updateStartup("正在启动分析服务", "就绪后将自动进入工作台。", 1);
  startWorker();
  startBackend();
  await waitFor(() => isBackendReady(backendPort), "分析服务", backend, 120000);
  fs.writeFileSync(stateFile, JSON.stringify({ desktop_pid: process.pid, backend_pid: backend.pid, worker_pid: worker.pid, queue_pid: queue.pid, backend_port: backendPort, db_port: dbPort, queue_port: queuePort, db_data: dbData }, null, 2));
  await updateStartup("正在打开工作台", "本地服务已就绪。", 2);
  await window.loadURL(`http://127.0.0.1:${backendPort}`);
}

app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("in-process-gpu");
app.disableHardwareAcceleration();
Menu.setApplicationMenu(null);
if (!app.requestSingleInstanceLock()) app.quit();

app.on("second-instance", () => {
  if (window) {
    if (window.isMinimized()) window.restore();
    window.focus();
  }
});
app.on("before-quit", shutdown);
app.on("window-all-closed", () => app.quit());
app.whenReady().then(async () => {
  try {
    await session.defaultSession.setProxy({ mode: "system" });
  } catch (error) {
    console.warn("CareerPilot 无法显式启用系统代理，将继续使用 Electron 默认网络设置。", error.message);
  }
  await launch();
}).catch(async (error) => {
  const detail = `${error.message}\n日志目录：${logRoot}`;
  if (window && !window.isDestroyed()) {
    await updateStartup("启动未完成", detail, -1, true).catch(() => {});
  }
  dialog.showErrorBox("职航启动失败", detail);
  await shutdown();
});
