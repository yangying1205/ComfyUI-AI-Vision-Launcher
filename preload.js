const { contextBridge, ipcRenderer } = require('electron');

// 为渲染进程暴露安全的API
contextBridge.exposeInMainWorld('electronAPI', {
    // 获取后端服务URL
    getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
    
    // 获取ComfyUI根目录路径
    getComfyUIPath: () => ipcRenderer.invoke('get-comfyui-path'),
    
    // 打开外部链接
    openExternal: (url) => ipcRenderer.invoke('open-external', url),
    
    // 显示文件夹选择对话框
    showFolderDialog: () => ipcRenderer.invoke('show-folder-dialog'),
    
    // 显示消息框
    showMessageBox: (options) => ipcRenderer.invoke('show-message-box', options),

    // 创建桌面快捷方式
    createDesktopShortcut: () => ipcRenderer.invoke('create-desktop-shortcut'),

    // 开机自启动设置
    setAutoStart: (enabled) => ipcRenderer.invoke('set-auto-start', enabled),
    getAutoStart: () => ipcRenderer.invoke('get-auto-start'),

    // 监听后端重启事件
    onBackendRestarted: (callback) => {
        ipcRenderer.on('backend-restarted', callback);
    },

    // 移除事件监听器
    removeAllListeners: (channel) => {
        ipcRenderer.removeAllListeners(channel);
    },

    // Git操作API
    gitSwitchVersion: (versionId) => ipcRenderer.invoke('git-switch-version', versionId),
    gitGetCurrentCommit: () => ipcRenderer.invoke('git-get-current-commit'),
    gitGetCommits: () => ipcRenderer.invoke('git-get-commits'),

    // 启动器更新API
    installLauncherUpdate: (zipFilePath) => ipcRenderer.invoke('install-launcher-update', zipFilePath),
    restartLauncher: () => ipcRenderer.invoke('restart-launcher')
});

// 为AI视界提供专用的工具函数
contextBridge.exposeInMainWorld('aiVisionAPI', {
    // 平台信息
    platform: process.platform,
    
    // 版本信息
    version: '1.0.0',
    
    // 应用名称
    appName: 'AI视界启动器',
    
    // 日志记录
    log: (...args) => {
        console.log('[AI Vision]', ...args);
    },
    
    // 错误记录
    error: (...args) => {
        console.error('[AI Vision Error]', ...args);
    },
    
    // 获取当前时间戳
    timestamp: () => new Date().toISOString(),
    
    // 格式化文件大小
    formatFileSize: (bytes) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },
    
    // 延迟函数
    delay: (ms) => new Promise(resolve => setTimeout(resolve, ms))
});