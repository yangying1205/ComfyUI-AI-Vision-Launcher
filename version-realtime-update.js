// 版本管理页面实时更新脚本
// 在版本切换后调用此函数更新页面显示

async function updateVersionDisplayAfterSwitch() {
    try {
        console.log('Updating version display after switch...');
        
        // 1. 清除版本缓存
        const clearResponse = await fetch('/comfyui/clear-version-cache', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (clearResponse.ok) {
            console.log('Version cache cleared');
        }
        
        // 2. 获取最新的版本数据（强制刷新）
        const versionsResponse = await fetch('/comfyui/versions?force_refresh=true');
        
        if (versionsResponse.ok) {
            const versionsData = await versionsResponse.json();
            
            if (versionsData.status === 'success') {
                console.log('Got fresh version data');
                
                // 3. 更新页面显示
                updateVersionTabs(versionsData);
                
                // 4. 显示成功消息
                showSuccessMessage('版本切换成功，页面已更新');
            } else {
                console.error('Failed to get version data:', versionsData.message);
            }
        }
        
    } catch (error) {
        console.error('Error updating version display:', error);
    }
}

function updateVersionTabs(versionsData) {
    // 更新稳定版本标签页
    if (versionsData.stable) {
        updateStableVersions(versionsData.stable);
    }
    
    // 更新开发版本标签页
    if (versionsData.development) {
        updateDevelopmentVersions(versionsData.development);
    }
}

function updateStableVersions(stableVersions) {
    // 更新稳定版本列表的当前版本标记
    const stableContainer = document.querySelector('#stable-versions-container');
    if (stableContainer) {
        // 重新渲染稳定版本列表
        renderVersionList(stableContainer, stableVersions, 'stable');
    }
}

function updateDevelopmentVersions(developmentVersions) {
    // 更新开发版本列表的当前版本标记
    const devContainer = document.querySelector('#development-versions-container');
    if (devContainer) {
        // 重新渲染开发版本列表
        renderVersionList(devContainer, developmentVersions, 'development');
    }
}

function renderVersionList(container, versions, type) {
    // 清空容器
    container.innerHTML = '';
    
    // 重新渲染版本列表
    versions.forEach(version => {
        const versionElement = createVersionElement(version, type);
        container.appendChild(versionElement);
    });
}

function createVersionElement(version, type) {
    const element = document.createElement('div');
    element.className = `version-item ${version.isCurrent ? 'current-version' : ''}`;
    
    element.innerHTML = `
        <div class="version-info">
            <div class="version-name">${version.version}</div>
            <div class="version-date">${version.date}</div>
            <div class="version-message">${version.message}</div>
            ${version.isCurrent ? '<span class="current-badge">当前版本</span>' : ''}
        </div>
        <div class="version-actions">
            ${!version.isCurrent ? `<button onclick="switchToVersion('${version.id}')" class="switch-btn">切换</button>` : ''}
        </div>
    `;
    
    return element;
}

function showSuccessMessage(message) {
    // 显示成功消息
    const messageDiv = document.createElement('div');
    messageDiv.className = 'success-message';
    messageDiv.textContent = message;
    messageDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #4CAF50;
        color: white;
        padding: 10px 20px;
        border-radius: 4px;
        z-index: 1000;
    `;
    
    document.body.appendChild(messageDiv);
    
    // 3秒后自动移除
    setTimeout(() => {
        document.body.removeChild(messageDiv);
    }, 3000);
}

// 修改原有的版本切换函数
async function switchToVersion(versionId) {
    try {
        // 显示加载状态
        showLoadingMessage('正在切换版本...');
        
        // 执行版本切换
        const response = await fetch('/comfyui/switch-version', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                version_id: versionId
            })
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            // 版本切换成功，更新页面显示
            await updateVersionDisplayAfterSwitch();
        } else {
            showErrorMessage(result.message || '版本切换失败');
        }
        
    } catch (error) {
        console.error('Version switch error:', error);
        showErrorMessage('版本切换失败: ' + error.message);
    } finally {
        hideLoadingMessage();
    }
}

function showLoadingMessage(message) {
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'loading-message';
    loadingDiv.textContent = message;
    loadingDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: rgba(0,0,0,0.8);
        color: white;
        padding: 20px;
        border-radius: 4px;
        z-index: 2000;
    `;
    
    document.body.appendChild(loadingDiv);
}

function hideLoadingMessage() {
    const loadingDiv = document.getElementById('loading-message');
    if (loadingDiv) {
        document.body.removeChild(loadingDiv);
    }
}

function showErrorMessage(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    errorDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #f44336;
        color: white;
        padding: 10px 20px;
        border-radius: 4px;
        z-index: 1000;
    `;
    
    document.body.appendChild(errorDiv);
    
    setTimeout(() => {
        document.body.removeChild(errorDiv);
    }, 5000);
}
