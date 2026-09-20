const { app, BrowserWindow, dialog } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
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
const pgBin = path.join(runtimeRoot, "postgresql", "bin");
const pgCtl = path.join(pgBin, "pg_ctl.exe");
const pgIsReady = path.join(pgBin, "pg_isready.exe");
const initdb = path.join(pgBin, "initdb.exe");
const backendExe = path.join(runtimeRoot, "backend", "CareerPilotBackend.exe");
const garnetExe = path.join(runtimeRoot, "garnet", "GarnetServer.exe");
const dotnetRoot = path.join(runtimeRoot, "dotnet");

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

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function findFreePort(preferred) {
  return new Promise((resolve, reject) => {
    let port = preferred;
    const tryPort = () => {
      const listener = net.createServer();
      listener.once("error", () => {
        listener.close();
        port += 1;
        if (port >= preferred + 100) reject(new Error("没有找到可用端口。"));
        else tryPort();
      });
      listener.listen(port, "127.0.0.1", () => listener.close(() => resolve(port)));
    };
    tryPort();
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

async function waitFor(check) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await check()) return;
    await sleep(500);
  }
  throw new Error("本地服务启动超时，请检查安装文件。 ");
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

function createWindow() {
  window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    show: false,
    icon: path.join(appRoot, "brand-mark.png"),
    webPreferences: { contextIsolation: true, zoomFactor: 0.9 },
  });
  window.once("ready-to-show", () => window.show());
  window.loadURL(`http://127.0.0.1:${backendPort}`);
}

async function launch() {
  fs.mkdirSync(logRoot, { recursive: true });
  stopPreviousRun();
  dbPort = await findFreePort(55432);
  startPostgres();
  await waitFor(() => isPostgresReady(dbPort));
  queuePort = await findFreePort(6379);
  startQueue();
  await waitFor(() => isQueueReady(queuePort));
  backendPort = await findFreePort(58080);
  startWorker();
  startBackend();
  await waitFor(() => isBackendReady(backendPort));
  fs.writeFileSync(stateFile, JSON.stringify({ desktop_pid: process.pid, backend_pid: backend.pid, worker_pid: worker.pid, queue_pid: queue.pid, backend_port: backendPort, db_port: dbPort, queue_port: queuePort, db_data: dbData }, null, 2));
  createWindow();
}

app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("in-process-gpu");
app.disableHardwareAcceleration();
if (!app.requestSingleInstanceLock()) app.quit();

app.on("second-instance", () => {
  if (window) {
    if (window.isMinimized()) window.restore();
    window.focus();
  }
});
app.on("before-quit", shutdown);
app.on("window-all-closed", () => app.quit());
app.whenReady().then(launch).catch(async (error) => {
  dialog.showErrorBox("职航启动失败", error.message);
  await shutdown();
});
