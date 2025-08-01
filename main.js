const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog, nativeImage } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs-extra');
const axios = require('axios'); // 确保axios已安装

class AIVisionLauncherApp {
    constructor() {
        this.mainWindow = null;
        this.tray = null;
        this.backendProcess = null;
        this.isQuitting = false;
        this.BACKEND_PORT = 8404; // 使用与原始项目相同的端口
        this.BACKEND_URL = `http://127.0.0.1:${this.BACKEND_PORT}`;
        this.isDev = process.argv.includes('--dev');
        
        // 性能优化：添加缓存
        this.gitCommitsCache = null;
        this.gitCacheTimestamp = 0;
        this.gitCacheTimeout = 60000; // 1分钟缓存
    }

    async init() {
        try {
            // 优化Electron启动选项
            app.commandLine.appendSwitch('--disable-gpu-sandbox');
            app.commandLine.appendSwitch('--disable-software-rasterizer');
            app.commandLine.appendSwitch('--disable-background-timer-throttling');
            app.commandLine.appendSwitch('--disable-backgrounding-occluded-windows');
            app.commandLine.appendSwitch('--disable-renderer-backgrounding');

            await app.whenReady();

            this.createMainWindow();
            this.createTray();

            await this.startBackendService();
            this.setupIPC();
            this.loadMainContent();
            this.setupAppEvents();

        } catch (error) {
            console.error('Fatal error during app initialization:', error);
            dialog.showErrorBox('应用启动失败', `发生致命错误: ${error.message}`);
            app.quit();
        }
    }

    createMainWindow() {
        // 创建高质量的窗口图标 - 专门解决任务栏模糊问题
        let windowIcon = null;

        try {
            // 直接使用原始512x512高分辨率PNG图标
            const originalPath = path.join(__dirname, 'assets', '01.png');
            if (fs.existsSync(originalPath)) {
                windowIcon = nativeImage.createFromPath(originalPath);
                console.log('使用原始512x512高分辨率图标');
            } else {
                // 回退到icon.png
                const pngPath = path.join(__dirname, 'assets', 'icon.png');
                if (fs.existsSync(pngPath)) {
                    windowIcon = nativeImage.createFromPath(pngPath);
                    console.log('使用高分辨率PNG图标');
                } else {
                    console.warn('未找到任何图标文件');
                }
            }
        } catch (error) {
            console.error('创建窗口图标失败:', error);
            windowIcon = null;
        }

        this.mainWindow = new BrowserWindow({
            width: 650,
            height: 950,
            minWidth: 600,
            minHeight: 900,
            title: 'AI视界启动器',
            webPreferences: {
                preload: path.join(__dirname, 'preload.js'),
                contextIsolation: true,
                nodeIntegration: false,
                // 优化选项以减少进程数量
                enableRemoteModule: false,
                webSecurity: true,
                allowRunningInsecureContent: false,
                experimentalFeatures: false,
                devTools: true  // 启用开发者工具
            },
            show: true, // 直接显示窗口
            center: true,
            backgroundColor: '#0a0a0f',
            icon: windowIcon, // 使用动态创建的高质量图标
        });

        this.mainWindow.once('ready-to-show', () => {
            console.log('Window ready to show');
            this.mainWindow.show();
            this.mainWindow.focus(); // 确保窗口获得焦点
            this.mainWindow.setAlwaysOnTop(true); // 临时置顶
            setTimeout(() => {
                this.mainWindow.setAlwaysOnTop(false); // 2秒后取消置顶
            }, 2000);

            // 开发者工具已关闭 - 正式使用时不需要控制台
            // this.mainWindow.webContents.openDevTools();
        });

        // 添加键盘快捷键支持
        this.mainWindow.webContents.on('before-input-event', (event, input) => {
            // F12 或 Ctrl+Shift+I 打开开发者工具
            if (input.key === 'F12' ||
                (input.control && input.shift && input.key === 'I')) {
                this.mainWindow.webContents.toggleDevTools();
            }
        });

        // 添加窗口显示事件监听
        this.mainWindow.on('show', () => {
            console.log('Window shown');
        });

        this.mainWindow.on('focus', () => {
            console.log('Window focused');
        });

        this.mainWindow.on('close', (event) => {
            if (!this.isQuitting) {
                event.preventDefault();
                this.mainWindow.hide();
            }
        });
        
        // 创建开发者菜单
        const template = [
            {
                label: '开发',
                submenu: [
                    {
                        label: '开发者工具',
                        accelerator: 'F12',
                        click: () => {
                            this.mainWindow.webContents.toggleDevTools();
                        }
                    },
                    {
                        label: '重新加载',
                        accelerator: 'Ctrl+R',
                        click: () => {
                            this.mainWindow.webContents.reload();
                        }
                    }
                ]
            }
        ];

        const menu = Menu.buildFromTemplate(template);
        Menu.setApplicationMenu(menu);
    }

    createTray() {
        let trayIcon;
        // 优先使用原始512x512高分辨率图标
        const iconPaths = [
            path.join(__dirname, 'assets', '01.png'),
            path.join(__dirname, 'assets', 'icon.png'),
            path.join(__dirname, 'assets', 'tray-icon.png')
        ];

        try {
            let iconPath = null;
            for (const p of iconPaths) {
                if (fs.existsSync(p)) {
                    iconPath = p;
                    break;
                }
            }

            if (iconPath) {
                trayIcon = nativeImage.createFromPath(iconPath);
                // 确保托盘图标有合适的尺寸
                if (iconPath.includes('icon.png')) {
                    // 如果使用主图标，调整到托盘合适的尺寸
                    trayIcon = trayIcon.resize({ width: 32, height: 32 });
                }
                console.log(`使用托盘图标: ${iconPath}`);
            } else {
                console.warn(`未找到图标文件，尝试的路径: ${iconPaths.join(', ')}`);
                trayIcon = nativeImage.createEmpty();
            }
        } catch (error) {
            console.error('创建托盘图标失败，使用空图标:', error);
            trayIcon = nativeImage.createEmpty();
        }

        this.tray = new Tray(trayIcon);
        const contextMenu = Menu.buildFromTemplate([
            { label: '显示', click: () => this.mainWindow.show() },
            { label: '重启服务', click: () => this.restartBackendService() },
            { type: 'separator' },
            { label: '退出', click: () => this.quit() }
        ]);
        this.tray.setToolTip('AI视界启动器');
        this.tray.setContextMenu(contextMenu);
        this.tray.on('double-click', () => this.mainWindow.show());
    }

    async startBackendService() {
        const pythonPath = this.findPythonExecutable();
        if (!pythonPath) {
            throw new Error('未找到Python可执行文件。');
        }

        // 关键修改：启动与原始项目一致的后端脚本
        const backendScript = path.join(__dirname, 'backend', 'start_fixed_cors.py');
        if (!fs.existsSync(backendScript)) {
            throw new Error(`后端脚本未找到: ${backendScript}`);
        }

        const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };

        console.log(`Spawning backend: ${pythonPath} ${backendScript}`);
        this.backendProcess = spawn(pythonPath, [backendScript], {
            cwd: path.join(__dirname, 'backend'),
            env: env,
        });

        this.backendProcess.stdout.on('data', (data) => console.log(`Backend stdout: ${data.toString().trim()}`));
        this.backendProcess.stderr.on('data', (data) => console.error(`Backend stderr: ${data.toString().trim()}`));
        this.backendProcess.on('error', (err) => { throw err; });

        // 关键修改：使用与原始项目一致的健康检查方式
        await this.waitForBackendReady();
        console.log('Backend service is ready.');
    }
    
    async waitForBackendReady(maxRetries = 30, interval = 1000) {
        console.log('Waiting for backend to be ready...');
        for (let i = 0; i < maxRetries; i++) {
            try {
                await axios.get(`${this.BACKEND_URL}/health`, { timeout: 900 });
                return; // 成功则直接返回
            } catch (error) {
                if (i === maxRetries - 1) {
                    throw new Error('后端服务启动失败或超时。');
                }
                await new Promise(resolve => setTimeout(resolve, interval));
            }
        }
    }

    findPythonExecutable() {
        // 便携包环境：launcher目录在便携包根目录下
        const portableRoot = path.dirname(__dirname);
        const candidates = [
            path.join(portableRoot, 'venv', 'Scripts', 'python.exe'),  // 优先使用虚拟环境
            path.join(portableRoot, 'venv', 'python.exe'),  // 备用虚拟环境路径
            path.join(portableRoot, 'venv', 'bin', 'python'),  // Linux/Mac兼容
            path.join(portableRoot, 'python', 'python.exe'),  // 便携Python作为后备
        ];
        for (const candidate of candidates) {
            if (fs.existsSync(candidate)) {
                 console.log(`Found Python in ComfyUI environment: ${candidate}`);
                 return candidate;
            }
        }
        
        console.warn("Could not find Python in ComfyUI's environment. Falling back to system Python.");
        const systemPythons = ['python', 'python3'];
        const { execSync } = require('child_process');
        for(const py of systemPythons) {
            try {
                execSync(`${py} --version`, { stdio: 'ignore' });
                console.log(`Using system Python: ${py}`);
                return py;
            } catch(e) { /* ignore */ }
        }
        return null;
    }

    async restartBackendService() {
        dialog.showMessageBox({ type: 'info', title: '提示', message: '正在重启后端服务...' });
        if (this.backendProcess) {
            this.backendProcess.kill();
            this.backendProcess = null;
        }
        try {
            await this.startBackendService();
            this.mainWindow.webContents.reload();
            dialog.showMessageBox({ type: 'info', title: '成功', message: '后端服务已重启。' });
        } catch (error) {
            dialog.showErrorBox('服务重启失败', error.message);
        }
    }
    
    restartApplication() {
        if (this.backendProcess) {
            this.backendProcess.kill();
        }
        app.relaunch();
        app.exit();
    }

    setupAppEvents() {
        app.on('window-all-closed', () => {
            if (process.platform !== 'darwin') this.quit();
        });
        app.on('activate', () => {
            if (BrowserWindow.getAllWindows().length === 0) this.init();
            else this.mainWindow.show();
        });
        app.on('before-quit', () => this.isQuitting = true);
    }

    setupIPC() {
        ipcMain.handle('get-backend-url', () => this.BACKEND_URL);
        ipcMain.handle('get-comfyui-path', () => path.join(path.dirname(__dirname), 'ComfyUI')); // 便携包环境：ComfyUI在便携包根目录下
        ipcMain.handle('open-external', (e, url) => shell.openExternal(url));
        ipcMain.handle('show-folder-dialog', () => dialog.showOpenDialog(this.mainWindow, { properties: ['openDirectory'] }));
        ipcMain.handle('show-message-box', (e, options) => dialog.showMessageBox(this.mainWindow, options));
        ipcMain.handle('create-desktop-shortcut', () => this.createDesktopShortcut());
        ipcMain.handle('set-auto-start', (e, enabled) => this.setAutoStart(enabled));
        ipcMain.handle('get-auto-start', () => this.getAutoStart());

        // 添加Git操作API
        ipcMain.handle('git-switch-version', (e, versionId) => this.gitSwitchVersion(versionId));
        ipcMain.handle('git-get-current-commit', () => this.gitGetCurrentCommit());
        ipcMain.handle('git-get-commits', (e, forceRefresh) => this.gitGetCommits(forceRefresh));
        ipcMain.handle('git-refresh-cache', () => {
            this.gitCommitsCache = null;
            this.gitCacheTimestamp = 0;
            return { status: 'success', message: '缓存已清空' };
        });

        // 添加启动器更新API
        ipcMain.handle('install-launcher-update', (e, zipFilePath) => this.installLauncherUpdate(zipFilePath));
        ipcMain.handle('restart-launcher', () => this.restartLauncher());
    }

    createDesktopShortcut() {
        try {
            const os = require('os');
            let desktopPath;

            // 尝试多种方式获取桌面路径
            if (process.platform === 'win32') {
                // Windows: 尝试多个可能的桌面路径
                const possiblePaths = [
                    path.join(os.homedir(), 'Desktop'),
                    path.join(os.homedir(), '桌面'),
                    process.env.USERPROFILE ? path.join(process.env.USERPROFILE, 'Desktop') : null,
                    process.env.USERPROFILE ? path.join(process.env.USERPROFILE, '桌面') : null
                ].filter(Boolean);

                desktopPath = possiblePaths.find(p => fs.existsSync(p));

                if (!desktopPath) {
                    throw new Error(`无法找到桌面路径。尝试的路径: ${possiblePaths.join(', ')}`);
                }
            } else {
                desktopPath = path.join(os.homedir(), 'Desktop');
            }

            console.log('使用桌面路径:', desktopPath);
            console.log('平台:', process.platform);
            console.log('用户目录:', os.homedir());

            if (process.platform === 'win32') {
                // Windows平台创建快捷方式
                return this.createWindowsShortcut(desktopPath);
            } else if (process.platform === 'darwin') {
                // macOS平台创建快捷方式
                return this.createMacShortcut(desktopPath);
            } else {
                // Linux平台创建快捷方式
                return this.createLinuxShortcut(desktopPath);
            }
        } catch (error) {
            console.error('创建桌面快捷方式失败:', error);
            return { success: false, error: error.message };
        }
    }

    createWindowsShortcut(desktopPath) {
        const { execSync } = require('child_process');
        const shortcutName = 'AI-Vision-Launcher.lnk';  // 使用英文名称避免编码问题
        const shortcutPath = path.join(desktopPath, shortcutName);

        // 获取当前可执行文件路径
        const exePath = process.execPath;
        const workingDir = path.dirname(exePath);

        console.log('创建Windows快捷方式:');
        console.log('桌面路径:', desktopPath);
        console.log('快捷方式路径:', shortcutPath);
        console.log('可执行文件路径:', exePath);
        console.log('工作目录:', workingDir);

        // 检查桌面路径是否存在
        if (!fs.existsSync(desktopPath)) {
            throw new Error(`桌面路径不存在: ${desktopPath}`);
        }

        try {
            // 获取应用根目录路径 - 应该是AI-Vision-Launcher目录，不是其父目录
            const appPath = __dirname; // 当前目录就是AI-Vision-Launcher目录

            console.log('__dirname:', __dirname);
            console.log('应用路径:', appPath);

            // 直接使用备用方法，因为它更可靠
            return this.createWindowsShortcutFallback(desktopPath, shortcutPath, exePath, appPath);

        } catch (error) {
            console.error('创建快捷方式失败:', error);
            throw error;
        }
    }

    createWindowsShortcutFallback(desktopPath, shortcutPath, exePath, workingDir) {
        const { execSync } = require('child_process');

        // 使用传入的workingDir作为应用路径
        const appPath = workingDir;

        console.log('应用路径:', appPath);
        console.log('可执行文件路径:', exePath);
        console.log('工作目录:', workingDir);

        // 验证路径是否正确
        if (!fs.existsSync(appPath)) {
            throw new Error(`应用路径不存在: ${appPath}`);
        }

        // 检查package.json是否存在（应该在AI-Vision-Launcher目录中）
        const packageJsonPath = path.join(appPath, 'package.json');
        console.log('检查package.json路径:', packageJsonPath);
        if (!fs.existsSync(packageJsonPath)) {
            console.warn(`package.json不存在: ${packageJsonPath}，但继续创建快捷方式`);
            // 不抛出错误，继续创建快捷方式
        }

        // 使用绝对路径并添加引号
        const quotedAppPath = `"${appPath}"`;
        const quotedExePath = `"${exePath}"`;

        // 使用VBScript创建快捷方式，避免PowerShell编码问题
        // Windows快捷方式必须使用ICO格式，按清晰度优先级尝试不同的ICO文件
        const iconPaths = [
            path.join(__dirname, 'assets', 'shortcut-icon-max.ico'),      // 最大质量
            path.join(__dirname, 'assets', 'shortcut-icon-ultra.ico'),   // 超清晰
            path.join(__dirname, 'assets', 'shortcut-48.ico'),           // 48x48专用
            path.join(__dirname, 'assets', 'shortcut-64.ico'),           // 64x64专用
            path.join(__dirname, 'assets', 'shortcut-32.ico'),           // 32x32专用
            path.join(__dirname, 'assets', 'shortcut-icon-alt.ico'),     // 备选方案
            path.join(__dirname, 'assets', 'shortcut-icon.ico'),         // 标准方案
            path.join(__dirname, 'assets', 'icon.ico')                   // 最后备选
        ];

        let iconPath = null;
        for (const testPath of iconPaths) {
            if (fs.existsSync(testPath)) {
                iconPath = testPath;
                const fileSize = fs.statSync(testPath).size;
                console.log(`使用Windows快捷方式ICO图标: ${testPath} (${fileSize} 字节)`);
                break;
            }
        }

        if (!iconPath) {
            console.warn('未找到任何可用的ICO图标文件，快捷方式可能显示为白色图标');
            // 创建一个临时的ICO文件
            iconPath = path.join(__dirname, 'assets', 'shortcut-icon.ico');
        }
        const vbScript = `Set WshShell = CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("${shortcutPath}")
Shortcut.TargetPath = "${exePath}"
Shortcut.Arguments = "${appPath}"
Shortcut.WorkingDirectory = "${appPath}"
Shortcut.IconLocation = "${iconPath}"
Shortcut.Description = "AI Vision Launcher - ComfyUI Management Tool"
Shortcut.Save
WScript.Echo "Shortcut created successfully"`;

        try {
            // 将VBScript写入临时文件
            const tempScriptPath = path.join(require('os').tmpdir(), 'create_shortcut.vbs');
            fs.writeFileSync(tempScriptPath, vbScript, 'utf8');

            // 执行VBScript
            const result = execSync(`cscript //NoLogo "${tempScriptPath}"`, {
                encoding: 'utf8',
                timeout: 10000
            });

            console.log('VBScript输出:', result);

            // 清理临时文件
            try {
                fs.unlinkSync(tempScriptPath);
            } catch (e) {
                console.warn('清理临时文件失败:', e.message);
            }

            // 验证快捷方式是否创建成功
            if (fs.existsSync(shortcutPath)) {
                return {
                    success: true,
                    message: '桌面快捷方式创建成功！',
                    path: shortcutPath
                };
            } else {
                throw new Error('快捷方式文件未找到，可能创建失败');
            }

        } catch (error) {
            console.error('VBScript执行失败:', error);
            throw new Error(`创建快捷方式失败: ${error.message}`);
        }
    }

    createMacShortcut(desktopPath) {
        const { execSync } = require('child_process');
        const appName = 'AI视界启动器';
        const aliasPath = path.join(desktopPath, `${appName}.app`);

        // 获取应用程序包路径
        const appPath = path.dirname(path.dirname(process.execPath));

        try {
            // 使用AppleScript创建别名
            const appleScript = `
                tell application "Finder"
                    make alias file to POSIX file "${appPath}" at desktop
                    set name of result to "${appName}"
                end tell
            `;

            execSync(`osascript -e '${appleScript}'`);
            return {
                success: true,
                message: '桌面快捷方式创建成功！',
                path: aliasPath
            };
        } catch (error) {
            throw new Error(`AppleScript执行失败: ${error.message}`);
        }
    }

    createLinuxShortcut(desktopPath) {
        const shortcutName = 'AI视界启动器.desktop';
        const shortcutPath = path.join(desktopPath, shortcutName);

        // 获取当前可执行文件路径
        const exePath = process.execPath;
        const workingDir = path.dirname(exePath);
        // 优先使用原始512x512高质量图标
        let iconPath = path.join(__dirname, 'assets', '01.png');
        if (!fs.existsSync(iconPath)) {
            iconPath = path.join(__dirname, 'assets', 'icon.png'); // 回退到icon.png
        }

        // 创建.desktop文件内容
        const desktopContent = `[Desktop Entry]
Version=1.0
Type=Application
Name=AI视界启动器
Comment=ComfyUI管理工具
Exec=${exePath}
Icon=${iconPath}
Path=${workingDir}
Terminal=false
StartupNotify=true
Categories=Development;Graphics;
`;

        try {
            fs.writeFileSync(shortcutPath, desktopContent, 'utf8');
            // 设置可执行权限
            fs.chmodSync(shortcutPath, 0o755);

            return {
                success: true,
                message: '桌面快捷方式创建成功！',
                path: shortcutPath
            };
        } catch (error) {
            throw new Error(`写入.desktop文件失败: ${error.message}`);
        }
    }

    loadMainContent() {
        this.mainWindow.loadFile('ai_vision_launcher.html');
        this.mainWindow.webContents.session.clearCache(() => {
            console.log('Application cache cleared.');
        });
    }

    quit() {
        this.isQuitting = true;
        if (this.backendProcess) {
            this.backendProcess.kill();
        }
        app.quit();
    }

    // 设置开机自启动
    setAutoStart(enabled) {
        try {
            if (process.platform === 'win32') {
                return this.setWindowsAutoStart(enabled);
            } else if (process.platform === 'darwin') {
                return this.setMacAutoStart(enabled);
            } else {
                return this.setLinuxAutoStart(enabled);
            }
        } catch (error) {
            console.error('设置开机自启动失败:', error);
            return { success: false, error: error.message };
        }
    }

    // 获取开机自启动状态
    getAutoStart() {
        try {
            if (process.platform === 'win32') {
                return this.getWindowsAutoStart();
            } else if (process.platform === 'darwin') {
                return this.getMacAutoStart();
            } else {
                return this.getLinuxAutoStart();
            }
        } catch (error) {
            console.error('获取开机自启动状态失败:', error);
            return { success: false, enabled: false, error: error.message };
        }
    }

    // Windows开机自启动设置
    setWindowsAutoStart(enabled) {
        const { execSync } = require('child_process');
        const appName = 'AI-Vision-Launcher';
        const exePath = process.execPath;
        const appPath = __dirname;

        try {
            if (enabled) {
                // 添加到注册表
                const regCommand = `reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "${appName}" /t REG_SZ /d "\\"${exePath}\\" \\"${appPath}\\"" /f`;
                execSync(regCommand, { encoding: 'utf8' });
                console.log('已添加到开机自启动');
            } else {
                // 从注册表删除
                const regCommand = `reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "${appName}" /f`;
                try {
                    execSync(regCommand, { encoding: 'utf8' });
                    console.log('已从开机自启动移除');
                } catch (e) {
                    // 如果项不存在，忽略错误
                    console.log('开机自启动项不存在或已移除');
                }
            }

            return { success: true, enabled: enabled };
        } catch (error) {
            throw new Error(`Windows开机自启动设置失败: ${error.message}`);
        }
    }

    // 获取Windows开机自启动状态
    getWindowsAutoStart() {
        const { execSync } = require('child_process');
        const appName = 'AI-Vision-Launcher';

        try {
            const regCommand = `reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "${appName}"`;
            execSync(regCommand, { encoding: 'utf8' });
            return { success: true, enabled: true };
        } catch (error) {
            // 如果查询失败，说明没有设置开机自启动
            return { success: true, enabled: false };
        }
    }

    // macOS开机自启动设置
    setMacAutoStart(enabled) {
        // macOS使用app.setLoginItemSettings
        app.setLoginItemSettings({
            openAtLogin: enabled,
            openAsHidden: false
        });

        return { success: true, enabled: enabled };
    }

    // 获取macOS开机自启动状态
    getMacAutoStart() {
        const loginSettings = app.getLoginItemSettings();
        return { success: true, enabled: loginSettings.openAtLogin };
    }

    // Linux开机自启动设置
    setLinuxAutoStart(enabled) {
        const os = require('os');
        const autostartDir = path.join(os.homedir(), '.config', 'autostart');
        const desktopFile = path.join(autostartDir, 'ai-vision-launcher.desktop');

        try {
            if (enabled) {
                // 确保autostart目录存在
                if (!fs.existsSync(autostartDir)) {
                    fs.mkdirSync(autostartDir, { recursive: true });
                }

                // 创建.desktop文件
                const desktopContent = `[Desktop Entry]
Type=Application
Name=AI Vision Launcher
Comment=ComfyUI Management Tool
Exec=${process.execPath} ${__dirname}
Icon=${path.join(__dirname, 'assets', 'tray-icon.png')}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
`;

                fs.writeFileSync(desktopFile, desktopContent, 'utf8');
                fs.chmodSync(desktopFile, 0o755);
            } else {
                // 删除.desktop文件
                if (fs.existsSync(desktopFile)) {
                    fs.unlinkSync(desktopFile);
                }
            }

            return { success: true, enabled: enabled };
        } catch (error) {
            throw new Error(`Linux开机自启动设置失败: ${error.message}`);
        }
    }

    // 获取Linux开机自启动状态
    getLinuxAutoStart() {
        const os = require('os');
        const desktopFile = path.join(os.homedir(), '.config', 'autostart', 'ai-vision-launcher.desktop');

        return { success: true, enabled: fs.existsSync(desktopFile) };
    }

    // Git操作方法
    async gitSwitchVersion(versionId) {
        const { execSync } = require('child_process');
        const comfyUIPath = path.join(path.dirname(__dirname), 'ComfyUI');

        try {
            console.log(`切换Git版本: ${versionId} 在路径: ${comfyUIPath}`);

            // 获取当前版本信息（切换前）
            const oldCommit = await this.gitGetCurrentCommit();

            // 重置Git状态，忽略工作目录中的更改
            console.log('重置Git工作目录状态...');
            try {
                execSync('git reset --hard HEAD', {
                    cwd: comfyUIPath,
                    encoding: 'utf8',
                    timeout: 30000
                });
                console.log('Git工作目录重置完成');
            } catch (resetError) {
                console.warn('Git重置警告:', resetError.message);
            }

            // 清理未跟踪的文件（可选）
            try {
                execSync('git clean -fd', {
                    cwd: comfyUIPath,
                    encoding: 'utf8',
                    timeout: 30000
                });
                console.log('清理未跟踪文件完成');
            } catch (cleanError) {
                console.warn('Git清理警告:', cleanError.message);
            }

            // 获取远程更新（确保有最新的commit）
            try {
                execSync('git fetch --all', {
                    cwd: comfyUIPath,
                    encoding: 'utf8',
                    timeout: 60000
                });
                console.log('获取远程更新完成');
            } catch (fetchError) {
                console.warn('Git fetch警告:', fetchError.message);
            }

            // 执行git checkout命令
            const result = execSync(`git checkout ${versionId}`, {
                cwd: comfyUIPath,
                encoding: 'utf8',
                timeout: 30000
            });

            console.log('Git切换成功:', result);

            // 版本切换后的修复操作
            await this.postVersionSwitchFix(comfyUIPath);

            // 清空Git缓存，因为版本已切换
            this.gitCommitsCache = null;
            this.gitCacheTimestamp = 0;
            console.log('版本切换后清空Git缓存');

            // 获取切换后的当前版本信息
            const currentCommit = await this.gitGetCurrentCommit();

            return {
                status: 'success',
                message: '版本切换成功',
                old_version: oldCommit || { commit: 'unknown' },
                new_version: currentCommit
            };
        } catch (error) {
            console.error('Git切换失败:', error);
            
            // 提供更详细的错误信息
            let errorMessage = `版本切换失败: ${error.message}`;
            if (error.message.includes('pathspec') && error.message.includes('did not match')) {
                errorMessage = `指定的版本号 ${versionId} 不存在。请确认版本号是否正确，或尝试先刷新版本列表。`;
            }

            return {
                status: 'error',
                message: errorMessage
            };
        }
    }

    // 版本切换后的修复操作
    async postVersionSwitchFix(comfyUIPath) {
        try {
            console.log('执行版本切换后修复操作...');

            // 确保hook_breaker_ac10a0.py文件存在
            const hookBreakerPath = path.join(comfyUIPath, 'hook_breaker_ac10a0.py');
            if (!fs.existsSync(hookBreakerPath)) {
                console.log('重新创建hook_breaker_ac10a0.py文件...');
                const hookBreakerContent = `# -*- coding: utf-8 -*-
"""
Hook Breaker Module - 钩子断路器模块
用于保存和恢复函数，防止自定义节点间的冲突
"""

import logging

# 存储原始函数的字典
_saved_functions = {}

logger = logging.getLogger(__name__)

def save_functions():
    """
    保存关键函数的原始状态
    在加载自定义节点之前调用，防止函数被修改
    """
    try:
        # 这里可以保存需要保护的关键函数
        # 例如：torch, numpy等关键库的函数
        
        logger.debug("Functions saved for hook breaking")
        
    except Exception as e:
        logger.warning(f"Failed to save functions: {e}")

def restore_functions():
    """
    恢复函数到原始状态
    在加载自定义节点之后调用，恢复被修改的函数
    """
    try:
        # 恢复被保存的函数
        # 如果有函数被自定义节点修改，在这里恢复
        
        logger.debug("Functions restored after hook breaking")
        
    except Exception as e:
        logger.warning(f"Failed to restore functions: {e}")

# 向后兼容性
def break_hooks():
    """向后兼容的函数名"""
    restore_functions()

def initialize():
    """初始化钩子断路器"""
    save_functions()

# 模块初始化时的默认行为
if __name__ == "__main__":
    print("Hook Breaker Module - 用于防止自定义节点函数冲突")`;

                fs.writeFileSync(hookBreakerPath, hookBreakerContent, 'utf8');
                console.log('✓ hook_breaker_ac10a0.py 文件已重新创建');
            }

            console.log('版本切换后修复操作完成');
        } catch (error) {
            console.warn('版本切换后修复操作出现警告:', error.message);
        }
    }

    async gitGetCurrentCommit() {
        const { execSync } = require('child_process');
        const comfyUIPath = path.join(path.dirname(__dirname), 'ComfyUI');

        try {
            const commitHash = execSync('git rev-parse HEAD', {
                cwd: comfyUIPath,
                encoding: 'utf8'
            }).trim();

            const commitShort = execSync('git rev-parse --short HEAD', {
                cwd: comfyUIPath,
                encoding: 'utf8'
            }).trim();

            const commitMessage = execSync('git log -1 --pretty=format:"%s"', {
                cwd: comfyUIPath,
                encoding: 'utf8'
            }).trim();

            const commitDate = execSync('git log -1 --pretty=format:"%ci"', {
                cwd: comfyUIPath,
                encoding: 'utf8'
            }).trim();

            return {
                status: 'success',
                commit_hash: commitHash,
                commit_short: commitShort,
                commit_message: commitMessage,
                commit_date: commitDate
            };
        } catch (error) {
            console.error('获取当前Git提交失败:', error);
            return {
                status: 'error',
                message: `获取当前提交失败: ${error.message}`
            };
        }
    }

    async gitGetCommits(forceRefresh = false) {
        const { execSync } = require('child_process');
        const comfyUIPath = path.join(path.dirname(__dirname), 'ComfyUI');
        const now = Date.now();

        // 检查缓存是否有效
        if (!forceRefresh && this.gitCommitsCache && (now - this.gitCacheTimestamp) < this.gitCacheTimeout) {
            console.log('使用Git提交历史缓存');
            return this.gitCommitsCache;
        }

        try {
            console.log('获取Git提交历史...');
            
            // 获取当前提交
            const currentCommit = execSync('git rev-parse --short HEAD', {
                cwd: comfyUIPath,
                encoding: 'utf8',
                timeout: 5000
            }).trim();

            // 获取提交历史 - 只获取当前分支，移除--all参数
            const gitLog = execSync('git log --oneline -100', {
                cwd: comfyUIPath,
                encoding: 'utf8',
                timeout: 10000
            });

            // 批量获取所有提交的详细信息 - 性能优化的关键
            const commitHashes = gitLog.trim().split('\n').map(line => {
                const [commit] = line.split(' ');
                return commit;
            }).filter(commit => commit && commit.length > 0);

            console.log(`获取到${commitHashes.length}个提交，正在批量获取详细信息...`);
            
            // 批量获取所有提交的日期和作者信息 - 移除--all参数
            const batchGitLog = execSync(`git log --pretty=format:"%h|%s|%ci|%an" -100`, {
                cwd: comfyUIPath,
                encoding: 'utf8',
                timeout: 15000
            });

            const detailMap = new Map();
            batchGitLog.trim().split('\n').forEach(line => {
                const [commit, message, date, author] = line.split('|');
                if (commit) {
                    detailMap.set(commit, { message, date, author });
                }
            });

            const commits = gitLog.trim().split('\n').map(line => {
                const [commit, ...messageParts] = line.split(' ');
                const message = messageParts.join(' ');
                const details = detailMap.get(commit) || {};

                return {
                    commit: commit,
                    message: details.message || message || '无提交信息',
                    date: details.date || new Date().toISOString(),
                    author: details.author || 'unknown',
                    is_current: commit === currentCommit
                };
            }).filter(commit => commit.commit && commit.commit.length > 0);

            const result = {
                status: 'success',
                commits: commits,
                total: commits.length,
                current_commit: currentCommit,
                cached: false
            };

            // 更新缓存
            this.gitCommitsCache = result;
            this.gitCacheTimestamp = now;
            
            console.log(`Git提交历史获取完成，共${commits.length}个提交`);
            return result;
        } catch (error) {
            console.error('获取Git提交历史失败:', error);
            
            // 如果有缓存，降级使用缓存
            if (this.gitCommitsCache) {
                console.log('Git操作失败，使用缓存数据');
                return { ...this.gitCommitsCache, cached: true, warning: '数据可能不是最新的' };
            }
            
            return {
                status: 'error',
                message: `获取提交历史失败: ${error.message}`,
                commits: []
            };
        }
    }

    // 启动器更新相关方法
    async installLauncherUpdate(zipFilePath) {
        try {
            console.log('开始安装启动器更新...');
            
            const AdmZip = require('adm-zip');
            
            // 1. 创建备份
            const backupDir = await this.createLauncherBackup();
            console.log(`备份创建完成: ${backupDir}`);
            
            // 2. 解压更新包
            const zip = new AdmZip(zipFilePath);
            const tempExtractDir = path.join(__dirname, '../temp_extract');
            
            if (fs.existsSync(tempExtractDir)) {
                fs.removeSync(tempExtractDir);
            }
            
            zip.extractAllTo(tempExtractDir, true);
            console.log('更新包解压完成');
            
            // 3. 验证更新包内容
            let sourceDir = tempExtractDir;
            
            // 检查是否有launcher子目录
            const launcherSubDir = path.join(tempExtractDir, 'launcher');
            if (fs.existsSync(launcherSubDir)) {
                sourceDir = launcherSubDir;
            }
            
            // 验证关键文件
            const keyFiles = ['package.json', 'main.js', 'ai_vision_launcher.html'];
            const missingFiles = keyFiles.filter(file => !fs.existsSync(path.join(sourceDir, file)));
            
            if (missingFiles.length > 0) {
                throw new Error(`更新包缺少关键文件: ${missingFiles.join(', ')}`);
            }
            
            // 4. 更新文件
            const filesToUpdate = [
                'main.js',
                'ai_vision_launcher.html',
                'package.json',
                'preload.js'
            ];
            
            for (const file of filesToUpdate) {
                const sourcePath = path.join(sourceDir, file);
                const targetPath = path.join(__dirname, file);
                
                if (fs.existsSync(sourcePath)) {
                    fs.copySync(sourcePath, targetPath);
                    console.log(`更新文件: ${file}`);
                }
            }
            
            // 5. 更新目录
            const dirsToUpdate = ['assets', 'backend'];
            for (const dir of dirsToUpdate) {
                const sourceDirPath = path.join(sourceDir, dir);
                const targetDirPath = path.join(__dirname, dir);
                
                if (fs.existsSync(sourceDirPath)) {
                    if (fs.existsSync(targetDirPath)) {
                        fs.removeSync(targetDirPath);
                    }
                    fs.copySync(sourceDirPath, targetDirPath);
                    console.log(`更新目录: ${dir}`);
                }
            }
            
            // 6. 清理临时文件
            fs.removeSync(tempExtractDir);
            if (fs.existsSync(zipFilePath)) {
                fs.removeSync(zipFilePath);
            }
            
            console.log('启动器更新安装完成');
            return { success: true, message: '更新安装成功' };
            
        } catch (error) {
            console.error('更新安装失败:', error);
            
            // 尝试回滚
            try {
                if (this.lastBackupDir) {
                    await this.rollbackLauncherUpdate(this.lastBackupDir);
                    console.log('已回滚到更新前状态');
                }
            } catch (rollbackError) {
                console.error('回滚失败:', rollbackError);
            }
            
            return { success: false, error: error.message };
        }
    }

    async createLauncherBackup() {
        const timestamp = Date.now();
        const backupDir = path.join(__dirname, '../launcher_backup_' + timestamp);
        
        // 备份关键文件和目录
        const backupItems = [
            'main.js',
            'ai_vision_launcher.html',
            'package.json',
            'preload.js',
            'assets',
            'backend'
        ];
        
        fs.ensureDirSync(backupDir);
        
        for (const item of backupItems) {
            const sourcePath = path.join(__dirname, item);
            const targetPath = path.join(backupDir, item);
            
            if (fs.existsSync(sourcePath)) {
                fs.copySync(sourcePath, targetPath);
            }
        }
        
        this.lastBackupDir = backupDir;
        return backupDir;
    }

    async rollbackLauncherUpdate(backupDir) {
        if (!fs.existsSync(backupDir)) {
            throw new Error('备份目录不存在');
        }
        
        // 恢复备份文件
        const items = fs.readdirSync(backupDir);
        for (const item of items) {
            const sourcePath = path.join(backupDir, item);
            const targetPath = path.join(__dirname, item);
            
            if (fs.existsSync(targetPath)) {
                fs.removeSync(targetPath);
            }
            fs.copySync(sourcePath, targetPath);
        }
        
        // 清理备份
        fs.removeSync(backupDir);
    }

    restartLauncher() {
        console.log('重启启动器...');
        app.relaunch();
        app.exit();
    }
}

const aiVisionApp = new AIVisionLauncherApp();
aiVisionApp.init();

process.on('uncaughtException', (error) => {
    console.error('Uncaught Exception:', error);
    dialog.showErrorBox('发生严重错误', error.message);
    app.quit();
});