const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
    onMessage: (cb) => ipcRenderer.on('ws-message', (_e, data) => cb(data)),
    send: (data) => ipcRenderer.send('ws-send', data),
});
