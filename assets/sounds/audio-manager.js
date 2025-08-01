/**
 * 科技主题音效管理器
 * Tech Theme Audio Manager for AI Vision Launcher
 */
class TechAudioManager {
    constructor() {
        this.audioContext = null;
        this.sounds = {};
        this.settings = {
            enabled: true,
            volume: 0.6,
            clickSounds: true,
            hoverSounds: false,
            feedbackSounds: true,
            systemSounds: true,
            theme: 'mech'
        };
        
        // 与原始项目完全一致的音效映射配置
        this.soundMap = {
            // UI交互音效 - 与原始项目保持一致
            'click': 'custom/按钮点击.WAV',                    // 普通按钮点击
            'click-primary': 'custom/按钮点击.WAV',            // 主要按钮点击
            'hover': 'custom/提醒、警告音效.WAV',                  // 悬停音效
            'input': 'custom/按钮点击.WAV',                    // 输入聚焦
            'switch': 'custom/导航标签点击的声音.WAV',              // 切换操作
            'tab-switch': 'custom/导航标签点击的声音.WAV',          // 标签页切换

            // 反馈音效
            'success': 'custom/任务完成音效.WAV',                  // 操作成功
            'complete': 'custom/操作成功反馈音效.WAV',              // 任务完成
            'confirm': 'custom/导航标签点击的声音.WAV',             // 确认操作
            'warning': 'custom/提醒、警告音效.WAV',                // 警告提示
            'error': 'custom/提醒、警告音效.WAV',                  // 错误提示
            'notification': 'custom/提醒、警告音效.WAV',           // 系统通知

            // 专用成功音效
            'plugin-success': 'custom/任务完成音效.WAV',           // 插件操作成功
            'version-success': 'custom/任务完成音效.WAV',          // 版本切换成功
            'install-success': 'custom/任务完成音效.WAV',          // 安装成功
            'update-success': 'custom/任务完成音效.WAV',           // 更新成功

            // 系统音效
            'startup': 'custom/启动程序音效.WAV',                  // 启动ComfyUI
            'startup-success': 'custom/任务完成音效.WAV',          // ComfyUI启动成功
            'shutdown': 'custom/关闭comfyui.WAV',                 // 关闭ComfyUI
            'shutdown-success': 'custom/comfyui关闭成功的音效.WAV', // ComfyUI关闭成功
            'app-close': 'custom/关闭comfyui.WAV',                // 关闭启动器
            'loading': 'custom/按钮科技音效.WAV'                   // 加载过程
        };
        
        this.init();
    }

    async init() {
        try {
            // 初始化Web Audio API
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();

            // 从localStorage加载设置
            this.loadSettings();

            // 使用与原始项目一致的配置
            console.log('Using audio configuration consistent with original project');

            // 清除可能存在的缓存
            this.sounds = {};

            // 预加载核心音效
            await this.preloadCoreSounds();

            console.log('TechAudioManager initialized successfully with synthetic sounds');
        } catch (error) {
            console.error('Failed to initialize TechAudioManager:', error);
        }
    }

    async loadConfigToolSettings() {
        try {
            console.log('正在检查音效配置工具的设置...');

            // 暂时跳过API加载，直接使用本地配置
            console.log('⚠️ 跳过API加载，使用默认配置避免控制台错误');
        } catch (error) {
            console.warn('加载音效配置工具设置失败:', error);
        }
    }



    loadSettings() {
        const saved = localStorage.getItem('audioSettings');
        if (saved) {
            this.settings = { ...this.settings, ...JSON.parse(saved) };
        }
    }

    saveSettings() {
        localStorage.setItem('audioSettings', JSON.stringify(this.settings));
    }

    async preloadCoreSounds() {
        // 预加载核心音效，包括所有常用的系统音效
        const coreSounds = [
            // UI交互音效
            'click', 'click-primary', 'tab-switch',
            // 反馈音效
            'success', 'error', 'warning',
            // 系统音效 - 确保ComfyUI相关音效被预加载
            'startup', 'startup-success', 'shutdown', 'shutdown-success', 'app-close',
            // 专用成功音效
            'plugin-success', 'version-success'
        ];

        console.log('🔄 预加载核心音效:', coreSounds);
        const promises = coreSounds.map(sound => this.loadSound(sound));
        await Promise.all(promises);
        console.log('✅ 核心音效预加载完成');
    }

    async loadSound(name) {
        if (!this.soundMap[name]) {
            console.warn(`Sound ${name} not found in sound map`);
            return;
        }

        try {
            // 使用正确的文件路径加载音效
            const soundPath = this.soundMap[name];
            const url = `assets/sounds/${soundPath}`;
            console.log(`Loading sound ${name} from: ${url}`);

            // 使用HTML5 Audio加载音效文件
            const audio = new Audio(url);
            audio.preload = 'auto';

            // 等待音频加载完成
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => {
                    reject(new Error('Audio loading timeout'));
                }, 5000);

                audio.addEventListener('canplaythrough', () => {
                    clearTimeout(timeout);
                    resolve();
                });

                audio.addEventListener('error', (e) => {
                    clearTimeout(timeout);
                    reject(e);
                });

                audio.load();
            });

            // 将HTML5 Audio对象存储
            this.sounds[name] = { type: 'html5', audio: audio };
            console.log(`Successfully loaded sound ${name} via HTML5 Audio`);

        } catch (error) {
            console.warn(`Failed to load sound file ${name}, using synthetic sound:`, error);
            this.generateSyntheticSound(name);
        }
    }

    generateSyntheticSound(name) {
        if (!this.audioContext) return;

        const sampleRate = this.audioContext.sampleRate;
        let duration, config;

        // 机甲游戏主题音效配置
        switch (name) {
            case 'click':
                duration = 0.12;
                config = {
                    type: 'metallic_click',
                    baseFreq: 1200,
                    harmonics: [1, 0.6, 0.3, 0.15],
                    attack: 0.01,
                    decay: 0.08,
                    noise: 0.1
                };
                break;
            case 'click-primary':
                duration = 0.18;
                config = {
                    type: 'power_click',
                    baseFreq: 800,
                    harmonics: [1, 0.8, 0.4, 0.2],
                    attack: 0.02,
                    decay: 0.12,
                    noise: 0.15,
                    sweep: { start: 800, end: 1200, curve: 2 }
                };
                break;
            case 'hover':
                duration = 0.08;
                config = {
                    type: 'scanner',
                    baseFreq: 1500,
                    harmonics: [1, 0.3],
                    attack: 0.02,
                    decay: 0.04,
                    noise: 0.05
                };
                break;
            case 'switch':
                duration = 0.25;
                config = {
                    type: 'mechanical_switch',
                    baseFreq: 600,
                    harmonics: [1, 0.7, 0.4, 0.2, 0.1],
                    attack: 0.03,
                    decay: 0.15,
                    noise: 0.2,
                    sweep: { start: 600, end: 400, curve: 1.5 }
                };
                break;
            case 'success':
                duration = 0.4;
                config = {
                    type: 'power_up',
                    baseFreq: 440,
                    harmonics: [1, 0.8, 0.6, 0.4, 0.2],
                    attack: 0.05,
                    decay: 0.25,
                    noise: 0.1,
                    sweep: { start: 440, end: 880, curve: 2 }
                };
                break;
            case 'error':
                duration = 0.5;
                config = {
                    type: 'alarm',
                    baseFreq: 200,
                    harmonics: [1, 0.9, 0.7, 0.5],
                    attack: 0.02,
                    decay: 0.3,
                    noise: 0.25,
                    modulation: { freq: 8, depth: 0.3 }
                };
                break;
            case 'warning':
                duration = 0.35;
                config = {
                    type: 'caution',
                    baseFreq: 300,
                    harmonics: [1, 0.8, 0.4],
                    attack: 0.03,
                    decay: 0.2,
                    noise: 0.2,
                    pulse: { freq: 12, duty: 0.6 }
                };
                break;
            case 'startup':
                duration = 1.2;
                config = {
                    type: 'boot_sequence',
                    baseFreq: 220,
                    harmonics: [1, 0.8, 0.6, 0.4, 0.3, 0.2],
                    attack: 0.1,
                    decay: 0.8,
                    noise: 0.15,
                    sweep: { start: 220, end: 660, curve: 3 }
                };
                break;
            case 'shutdown':
                duration = 0.8;
                config = {
                    type: 'power_down',
                    baseFreq: 660,
                    harmonics: [1, 0.7, 0.5, 0.3],
                    attack: 0.05,
                    decay: 0.6,
                    noise: 0.1,
                    sweep: { start: 660, end: 110, curve: 2 }
                };
                break;
            default:
                duration = 0.12;
                config = {
                    type: 'metallic_click',
                    baseFreq: 1200,
                    harmonics: [1, 0.6, 0.3],
                    attack: 0.01,
                    decay: 0.08,
                    noise: 0.1
                };
        }

        this.sounds[name] = this.createMechSound(duration, config);
    }

    createMechSound(duration, config) {
        const sampleRate = this.audioContext.sampleRate;
        const buffer = this.audioContext.createBuffer(1, sampleRate * duration, sampleRate);
        const data = buffer.getChannelData(0);

        for (let i = 0; i < data.length; i++) {
            const t = i / sampleRate;
            const progress = t / duration;
            let value = 0;

            // 基础频率（可能有频率扫描）
            let freq = config.baseFreq;
            if (config.sweep) {
                const sweepProgress = Math.pow(progress, config.sweep.curve);
                freq = config.sweep.start + (config.sweep.end - config.sweep.start) * sweepProgress;
            }

            // 生成谐波
            config.harmonics.forEach((amplitude, index) => {
                const harmonic = (index + 1);
                value += Math.sin(2 * Math.PI * freq * harmonic * t) * amplitude;
            });

            // 添加调制（如警报音效）
            if (config.modulation) {
                const mod = 1 + Math.sin(2 * Math.PI * config.modulation.freq * t) * config.modulation.depth;
                value *= mod;
            }

            // 添加脉冲效果
            if (config.pulse) {
                const pulsePhase = (t * config.pulse.freq) % 1;
                if (pulsePhase > config.pulse.duty) {
                    value *= 0.3;
                }
            }

            // 添加噪声（机械质感）
            if (config.noise > 0) {
                const noise = (Math.random() - 0.5) * 2 * config.noise;
                value += noise;
            }

            // 应用包络
            let envelope = 1;
            if (progress < config.attack) {
                envelope = progress / config.attack;
            } else {
                const decayProgress = (progress - config.attack) / (1 - config.attack);
                envelope = Math.exp(-decayProgress * (1 / config.decay) * 3);
            }

            // 添加机甲特有的金属质感（高频谐波衰减）
            const metallicFilter = Math.exp(-progress * 2);
            envelope *= (0.7 + 0.3 * metallicFilter);

            data[i] = value * envelope * 0.25; // 降低整体音量避免失真
        }

        return buffer;
    }

    play(soundName, volume = null) {
        if (!this.settings.enabled) return;

        // 检查特定音效类型是否启用
        if (soundName.includes('hover') && !this.settings.hoverSounds) return;
        if (['success', 'error', 'warning', 'notification'].includes(soundName) && !this.settings.feedbackSounds) return;
        if (['startup', 'shutdown', 'complete'].includes(soundName) && !this.settings.systemSounds) return;
        if (['click', 'switch', 'input', 'tab-switch'].includes(soundName) && !this.settings.clickSounds) return;

        let sound = this.sounds[soundName];
        if (!sound) {
            // 如果音效未加载，立即生成合成音效
            this.generateSyntheticSound(soundName);
            sound = this.sounds[soundName];
        }

        if (!sound) {
            console.warn(`Failed to generate sound: ${soundName}`);
            return;
        }

        try {
            const targetVolume = (volume !== null ? volume : this.settings.volume) * 0.3;

            // 检查是否是HTML5 Audio对象
            if (sound.type === 'html5') {
                const audio = sound.audio.cloneNode();
                audio.volume = targetVolume;
                audio.currentTime = 0; // 重置播放位置
                audio.play().catch(e => console.log(`HTML5 Audio play failed for ${soundName}:`, e));
                return;
            }

            // 使用Web Audio API播放合成音效
            if (this.audioContext && sound instanceof AudioBuffer) {
                const source = this.audioContext.createBufferSource();
                const gainNode = this.audioContext.createGain();

                source.buffer = sound;
                gainNode.gain.value = targetVolume;

                source.connect(gainNode);
                gainNode.connect(this.audioContext.destination);
                source.start();
            }

        } catch (error) {
            console.error(`Failed to play sound ${soundName}:`, error);
        }
    }

    // 设置方法
    setEnabled(enabled) {
        this.settings.enabled = enabled;
        this.saveSettings();
    }

    setVolume(volume) {
        this.settings.volume = Math.max(0, Math.min(1, volume));
        this.saveSettings();
    }

    setClickSounds(enabled) {
        this.settings.clickSounds = enabled;
        this.saveSettings();
    }

    setHoverSounds(enabled) {
        this.settings.hoverSounds = enabled;
        this.saveSettings();
    }

    setFeedbackSounds(enabled) {
        this.settings.feedbackSounds = enabled;
        this.saveSettings();
    }

    setSystemSounds(enabled) {
        this.settings.systemSounds = enabled;
        this.saveSettings();
    }

    // 获取设置
    getSettings() {
        return { ...this.settings };
    }

    // 预览音效
    preview(soundName) {
        this.play(soundName, 0.7);
    }
}

// 全局音效管理器实例
window.audioManager = new TechAudioManager();

// 自动初始化音效管理器
document.addEventListener('DOMContentLoaded', async () => {
    try {
        await window.audioManager.init();
        console.log('音效管理器自动初始化完成');
    } catch (error) {
        console.error('音效管理器初始化失败:', error);
    }
});
