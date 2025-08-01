/**
 * 版本管理页面优化脚本
 * 解决版本信息显示问题和加载性能问题
 */

class VersionManagementOptimizer {
    constructor() {
        this.versionCache = null;
        this.versionCacheExpiry = 0;
        this.cacheDuration = 300000; // 5分钟缓存
        this.currentVersionType = 'development';
        this.isLoading = false;
        
        // 性能监控
        this.performanceMetrics = {
            lastLoadTime: 0,
            loadCount: 0,
            cacheHitCount: 0
        };
    }

    // 优化的版本数据获取方法
    async fetchVersionData(forceRefresh = false) {
        const now = Date.now();
        
        // 首次加载时总是强制获取远程数据，确保显示最新版本
        const shouldForceRefresh = forceRefresh || !this.versionCache;
        
        // 智能缓存检查（仅在非首次加载且不强制刷新时使用）
        if (!shouldForceRefresh && this.isValidCache()) {
            console.log('🚀 使用缓存版本数据 (剩余时间: ' + Math.round((this.versionCacheExpiry - now) / 1000) + 's)');
            this.performanceMetrics.cacheHitCount++;
            return this.versionCache;
        }

        const startTime = performance.now();
        console.log(`🚀 获取版本数据${shouldForceRefresh ? ' (强制刷新获取远程版本)' : ''}...`);

        try {
            // 优化的API请求参数 - 使用新的后端API
            const params = new URLSearchParams({
                force_refresh: shouldForceRefresh,  // 使用计算后的强制刷新标志
                limit_stable: '15',                 // 减少数据量提升加载速度
                limit_development: '25'             // 减少数据量提升加载速度
            });

            const response = await fetch(`${window.launcherInstance?.backendUrl || 'http://127.0.0.1:8404'}/comfyui/versions?${params}`, {
                headers: {
                    'Cache-Control': shouldForceRefresh ? 'no-cache' : 'max-age=30',
                    'Accept': 'application/json',
                    'X-Request-Source': 'version-optimizer'
                },
                signal: AbortSignal.timeout(10000) // 10秒超时，提升响应速度
            });

            if (!response.ok) {
                throw new Error(`API错误: ${response.status} ${response.statusText}`);
            }

            const rawData = await response.json();
            console.log('📦 原始API响应:', rawData);
            
            const processedData = this.processVersionData(rawData);
            
            // 更新缓存
            this.versionCache = processedData;
            this.versionCacheExpiry = now + this.cacheDuration;
            
            const endTime = performance.now();
            this.performanceMetrics.lastLoadTime = endTime - startTime;
            this.performanceMetrics.loadCount++;
            
            console.log(`✅ 版本数据获取完成 (${this.performanceMetrics.lastLoadTime.toFixed(2)}ms)`);
            console.log(`📊 处理后数据: 稳定版${processedData.stable.length}个, 开发版${processedData.development.length}个`);
            
            return processedData;

        } catch (error) {
            console.error('版本数据获取失败:', error);
            
            // 降级策略
            if (this.versionCache) {
                console.warn('⚠️ 使用过期缓存数据');
                return this.versionCache;
            }
            
            return this.getFallbackVersionData();
        }
    }

    // 数据处理和验证
    processVersionData(rawData) {
        if (!rawData || rawData.status !== 'success') {
            throw new Error('无效的版本数据格式');
        }

        const processedData = {
            stable: Array.isArray(rawData.stable) ? rawData.stable : [],
            development: Array.isArray(rawData.development) ? rawData.development : [],
            current_commit: rawData.current_commit || 'unknown',
            current_branch: rawData.current_branch || 'main',
            last_updated: Date.now()
        };

        // 修复版本信息显示问题：确保当前版本被正确标记
        this.markCurrentVersion(processedData);
        
        console.log(`📦 版本数据处理完成: 稳定版${processedData.stable.length}个, 开发版${processedData.development.length}个`);
        return processedData;
    }

    // 标记当前版本
    markCurrentVersion(data) {
        const currentCommit = data.current_commit;
        let foundCurrent = false;

        // 在稳定版本中标记当前版本
        data.stable = data.stable.map(version => {
            const isCurrent = version.id === currentCommit || version.commit === currentCommit;
            if (isCurrent) foundCurrent = true;
            return { ...version, current: isCurrent, isStable: true };
        });

        // 在开发版本中标记当前版本
        data.development = data.development.map(version => {
            const isCurrent = version.id === currentCommit || version.commit === currentCommit;
            if (isCurrent) foundCurrent = true;
            return { ...version, current: isCurrent, isStable: false };
        });

        // 如果未找到当前版本，添加到开发版本列表
        if (!foundCurrent && currentCommit !== 'unknown') {
            console.warn(`⚠️ 当前版本 ${currentCommit} 未在版本列表中找到，添加到开发版本`);
            data.development.unshift({
                id: currentCommit,
                commit: currentCommit,
                commit_short: currentCommit.substring(0, 8),
                message: '当前版本',
                date: new Date().toISOString().split('T')[0],
                author: 'Current',
                current: true,
                isStable: false
            });
        }
    }

    // 缓存有效性检查
    isValidCache() {
        return this.versionCache && 
               this.versionCacheExpiry && 
               Date.now() < this.versionCacheExpiry;
    }

    // 降级数据
    getFallbackVersionData() {
        console.log('📦 使用降级版本数据');
        return {
            stable: [{
                id: 'fallback-stable',
                version: '稳定版本',
                message: '网络连接问题，无法获取详细版本信息',
                date: new Date().toISOString().split('T')[0],
                author: 'System',
                current: false,
                isStable: true
            }],
            development: [{
                id: 'fallback-dev',
                commit: 'current',
                commit_short: 'current',
                message: '当前开发版本',
                date: new Date().toISOString().split('T')[0],
                author: 'Current',
                current: true,
                isStable: false
            }],
            current_commit: 'current',
            current_branch: 'main',
            is_fallback: true
        };
    }

    // 高性能版本列表渲染
    async renderVersionList(containerId, versions, type) {
        const container = document.getElementById(containerId);
        if (!container || !Array.isArray(versions)) return;

        // 使用DocumentFragment避免多次DOM重排
        const fragment = document.createDocumentFragment();
        
        // 批量创建元素
        const elements = await this.createVersionElements(versions, type);
        elements.forEach(el => fragment.appendChild(el));
        
        // 一次性更新DOM
        container.innerHTML = '';
        container.appendChild(fragment);
        
        console.log(`✅ ${type}版本列表渲染完成: ${versions.length}个版本`);
    }

    // 创建版本元素
    async createVersionElements(versions, type) {
        return versions.map(version => {
            const versionEl = document.createElement('div');
            versionEl.className = `version-item ${version.current ? 'current' : ''}`;
            versionEl.setAttribute('data-version', version.id || version.commit);
            versionEl.setAttribute('data-type', type);

            const isStable = type === 'stable';
            const displayId = isStable ? (version.version || version.id) : (version.commit_short || version.id);
            const statusIcon = version.current ? '<i class="fas fa-check-circle current-icon"></i>' : '';
            
            versionEl.innerHTML = `
                <div class="version-info">
                    <div class="version-header">
                        <span class="version-id">${displayId}</span>
                        ${statusIcon}
                        <span class="version-type-badge ${type}">${isStable ? '稳定' : '开发'}</span>
                    </div>
                    <div class="version-message">${version.message || '无描述'}</div>
                    <div class="version-meta">
                        <span class="version-date">${version.date}</span>
                        <span class="version-author">${version.author}</span>
                    </div>
                </div>
                <div class="version-actions">
                    <button class="version-switch-btn" 
                            onclick="versionOptimizer.switchToVersion('${version.id || version.commit}', '${displayId}')"
                            ${version.current ? 'disabled' : ''}>
                        ${version.current ? '当前版本' : '切换'}
                    </button>
                </div>
            `;

            return versionEl;
        });
    }

    // 版本切换
    async switchToVersion(versionId, displayId) {
        try {
            console.log(`🔄 切换到版本: ${versionId} (${displayId})`);
            
            const confirmed = confirm(`确定要切换到版本 ${displayId} 吗？\n\n这将更改ComfyUI的版本，可能需要重启。`);
            if (!confirmed) return;

            const response = await fetch(`${window.launcherInstance?.backendUrl || 'http://127.0.0.1:8404'}/comfyui/switch-version`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    version_id: versionId,
                    version_type: 'commit'
                })
            });

            if (!response.ok) {
                throw new Error(`版本切换失败: ${response.status}`);
            }

            const result = await response.json();
            if (result.status === 'success') {
                // 清除缓存
                this.versionCache = null;
                this.versionCacheExpiry = 0;
                
                // 更新显示
                await this.refreshVersionDisplay();
                
                alert(`✅ 版本切换成功！\n当前版本: ${displayId}`);
            } else {
                throw new Error(result.message || '版本切换失败');
            }

        } catch (error) {
            console.error('版本切换失败:', error);
            alert(`❌ 版本切换失败: ${error.message}`);
        }
    }

    // 刷新版本显示
    async refreshVersionDisplay() {
        try {
            const versionData = await this.fetchVersionData(true);
            
            await Promise.all([
                this.renderVersionList('stable-versions', versionData.stable, 'stable'),
                this.renderVersionList('development-versions', versionData.development, 'development')
            ]);
            
            this.updateCurrentVersionIndicator();
            
        } catch (error) {
            console.error('刷新版本显示失败:', error);
        }
    }

    // 更新当前版本指示器
    updateCurrentVersionIndicator() {
        const currentItems = document.querySelectorAll('.version-item.current');
        console.log(`📍 当前版本标记数量: ${currentItems.length}`);
        
        if (currentItems.length !== 1) {
            console.warn('⚠️ 当前版本标记异常，进行修复');
            this.fixCurrentVersionDisplay();
        }
    }

    // 修复当前版本显示
    fixCurrentVersionDisplay() {
        if (!this.versionCache) return;

        const currentCommit = this.versionCache.current_commit;
        const allItems = document.querySelectorAll('.version-item');
        
        allItems.forEach(item => {
            const itemVersion = item.getAttribute('data-version');
            const isCurrent = itemVersion === currentCommit;
            
            item.classList.toggle('current', isCurrent);
            const switchBtn = item.querySelector('.version-switch-btn');
            if (switchBtn) {
                switchBtn.disabled = isCurrent;
                switchBtn.textContent = isCurrent ? '当前版本' : '切换';
            }
        });
    }

    // 性能统计
    getPerformanceStats() {
        return {
            ...this.performanceMetrics,
            cacheHitRate: this.performanceMetrics.loadCount > 0 ? 
                (this.performanceMetrics.cacheHitCount / this.performanceMetrics.loadCount * 100).toFixed(1) + '%' : '0%'
        };
    }
}

// 创建全局实例
window.versionOptimizer = new VersionManagementOptimizer();

// 自动初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('📦 版本管理优化脚本已加载');
});

// 导出供外部使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = VersionManagementOptimizer;
}