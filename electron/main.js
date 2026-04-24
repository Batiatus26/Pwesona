const { app, BrowserWindow, screen, globalShortcut } = require('electron');
const path = require('path');

let win;

function createWindow() {
    const { width, height } = screen.getPrimaryDisplay().bounds;

    win = new BrowserWindow({
        width,
        height,
        x: 0,
        y: 0,
        fullscreen: true,
        frame: false,
        alwaysOnTop: true,
        transparent: false,
        backgroundColor: '#070a0e',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
        },
    });

    win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
    win.setMenuBarVisibility(false);

    // ESC and Alt+F4 exit
    win.webContents.on('before-input-event', (_event, input) => {
        if (input.type === 'keyDown') {
            if (input.key === 'Escape') app.quit();
            if (input.key === 'F4' && input.alt) app.quit();
        }
    });
}

app.whenReady().then(() => {
    createWindow();
    // Global ESC fallback
    globalShortcut.register('Escape', () => app.quit());
});

app.on('window-all-closed', () => app.quit());
app.on('will-quit', () => globalShortcut.unregisterAll());
