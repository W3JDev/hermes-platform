const { app, BrowserWindow, shell } = require('electron');
const path = require('path');

// OpenMuse frontdoor UI. Defaults to the local server (PORT 8787).
// Point at a remote deployment with HERMES_DESKTOP_URL, e.g.
// HERMES_DESKTOP_URL=http://hermes-platform-0ascn6-73c05b-169-58-147-169.sslip.io
const TARGET_URL = process.env.HERMES_DESKTOP_URL || 'http://localhost:8787';

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 850,
    minWidth: 380,
    minHeight: 600,
    title: 'Hermes Muse',
    backgroundColor: '#09090b',
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  win.loadURL(TARGET_URL).catch((err) => {
    console.error(`[hermes-desktop] Could not reach ${TARGET_URL}:`, err.message);
  });

  // Handle external links safely
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
