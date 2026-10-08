const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("careerPilotUpdates", {
  version: () => ipcRenderer.invoke("updates:version"),
  check: () => ipcRenderer.invoke("updates:check"),
  install: () => ipcRenderer.invoke("updates:install"),
  onProgress: (listener) => {
    const handler = (_event, progress) => listener(progress);
    ipcRenderer.on("updates:progress", handler);
    return () => ipcRenderer.removeListener("updates:progress", handler);
  },
});
