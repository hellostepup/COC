// Electron shell: starts the Python backend, waits for it, then opens the dashboard.
const { app, BrowserWindow, shell, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const net = require("net");
const http = require("http");
const fs = require("fs");

const DEV = !!process.env.ELECTRON_DEV;
let backend = null;
let win = null;

function freePort(preferred) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once("error", () => {
      const s2 = net.createServer();
      s2.listen(0, "127.0.0.1", () => { const p = s2.address().port; s2.close(() => resolve(p)); });
    });
    s.listen(preferred, "127.0.0.1", () => s.close(() => resolve(preferred)));
  });
}

function backendCommand(port) {
  const args = ["--port", String(port)];
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", process.platform === "win32" ? "coc-backend.exe" : "coc-backend");
    return { cmd: exe, args, env: { COC_MANAGER_STATIC: path.join(__dirname, "..", "dist") } };
  }
  const root = path.join(__dirname, "..", "..", "backend");
  const py = process.platform === "win32" ? path.join(root, ".venv", "Scripts", "python.exe") : path.join(root, ".venv", "bin", "python");
  return { cmd: fs.existsSync(py) ? py : "python", args: [path.join(root, "run.py"), ...args], env: {} };
}

function waitForHealth(port, timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      http.get({ host: "127.0.0.1", port, path: "/api/health", timeout: 1000 }, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        retry();
      }).on("error", retry);
    };
    const retry = () => (Date.now() - start > timeoutMs ? reject(new Error("Backend did not start")) : setTimeout(tryOnce, 300));
    tryOnce();
  });
}

async function start() {
  const port = DEV ? 8765 : await freePort(8765);
  const { cmd, args, env } = backendCommand(port);
  let stderr = "";
  backend = spawn(cmd, args, { env: { ...process.env, ...env }, windowsHide: true });
  backend.stderr.on("data", (d) => { stderr = (stderr + d.toString()).slice(-4000); });
  backend.on("exit", (code) => { if (code && !app.isQuitting) dialog.showErrorBox("Backend stopped", `Exit code ${code}\n\n${stderr}`); });

  win = new BrowserWindow({
    width: 1400, height: 900, minWidth: 1000, minHeight: 650, backgroundColor: "#0e121a",
    title: "COC Farming Manager", autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });

  try {
    await waitForHealth(port);
  } catch (e) {
    dialog.showErrorBox("Could not start", `${e.message}\n\n${stderr}`);
    app.quit();
    return;
  }
  win.loadURL(DEV ? "http://localhost:5173" : `http://127.0.0.1:${port}`);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.setAppUserModelId("local.cocmanager.app"); // needed for Windows toast notifications
  app.whenReady().then(start);
  app.on("before-quit", () => { app.isQuitting = true; if (backend) backend.kill(); });
  app.on("window-all-closed", () => app.quit());
}
