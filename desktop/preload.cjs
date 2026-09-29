const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("careerPilotUpdates", {
  check: () => ipcRenderer.invoke("updates:check"),
  install: () => ipcRenderer.invoke("updates:install"),
});
