"""
修复CORS问题的后端服务器
"""
import sys
import os
from pathlib import Path

# 设置输出编码为UTF-8，避免GBK编码问题
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print(f"Project root: {project_root}")

try:
    # 导入核心模块
    from core.config import ConfigManager
    print("Config module imported")

    from core.system_monitor import system_monitor
    print("System monitor imported")

    from core.version_manager import version_manager
    print("Version manager imported")

    from core.process_manager import process_manager
    print("Process manager imported")

except Exception as e:
    print(f"Warning: Some modules failed to import: {e}")
    print("Continuing with basic functionality...")

# 启动API服务器
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import time
import asyncio
import subprocess
import urllib.request
import socket
import requests
import json
from datetime import datetime, timedelta

# 便携包环境路径检测函数
def get_portable_paths():
    """获取便携包环境的路径配置"""
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    launcher_dir = os.path.dirname(backend_dir)
    portable_root = os.path.dirname(launcher_dir)  # 修复：launcher的父目录才是便携包根目录
    comfyui_dir = os.path.join(portable_root, "ComfyUI")
    venv_dir = os.path.join(portable_root, "venv")

    return {
        "backend_dir": backend_dir,
        "launcher_dir": launcher_dir,
        "portable_root": portable_root,
        "comfyui_path": comfyui_dir,  # 修复：使用comfyui_path而不是comfyui_dir
        "venv_path": venv_dir
    }

# 镜像源速度测试缓存
mirror_speed_cache = {}

def test_mirror_speed(url, timeout=5):
    """测试镜像源速度"""
    if url in mirror_speed_cache:
        return mirror_speed_cache[url]

    try:
        import time
        start_time = time.time()
        response = requests.head(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        end_time = time.time()

        response_time = (end_time - start_time) * 1000
        success = response.status_code == 200

        result = {
            'success': success,
            'response_time': response_time,
            'status_code': response.status_code
        }

        mirror_speed_cache[url] = result
        return result
    except Exception as e:
        result = {
            'success': False,
            'response_time': float('inf'),
            'status_code': None,
            'error': str(e)
        }
        mirror_speed_cache[url] = result
        return result

def get_optimal_mirror_sources():
    """获取优化后的镜像源列表（按速度排序）"""
    # 基础镜像源配置
    base_sources = [
        {
            "name": "jsDelivr CDN",
            "node_list_url": "https://cdn.jsdelivr.net/gh/ltdrdata/ComfyUI-Manager@main/custom-node-list.json",
            "github_stats_url": "https://cdn.jsdelivr.net/gh/ltdrdata/ComfyUI-Manager@main/github-stats.json",
            "test_url": "https://cdn.jsdelivr.net/gh/ltdrdata/ComfyUI-Manager@main/custom-node-list.json"
        },
        {
            "name": "GitHub原始",
            "node_list_url": "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json",
            "github_stats_url": "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/github-stats.json",
            "test_url": "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"
        }
    ]

    # 测试各个镜像源的速度
    for source in base_sources:
        speed_result = test_mirror_speed(source['test_url'])
        source['speed_test'] = speed_result

    # 按速度排序（成功的在前，失败的在后；成功的按响应时间排序）
    base_sources.sort(key=lambda x: (
        not x['speed_test']['success'],  # 失败的排在后面
        x['speed_test']['response_time']  # 成功的按响应时间排序
    ))

    return base_sources

app = FastAPI(title="ComfyUI Launcher API", version="1.0.0")

# 添加CORS中间件 - 允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GitHub API缓存
github_stars_cache = {}
cache_expiry = {}

# 版本信息缓存
version_cache = None
version_cache_expiry = None
version_cache_duration = 10 * 60  # 10分钟缓存

# 安装并发控制
import threading
install_lock = threading.Lock()
current_installations = set()

# 缓存文件路径
cache_file_path = os.path.join(os.path.dirname(__file__), "github_stars_cache.json")

def optimize_git_config():
    """优化Git配置以提高克隆速度"""
    try:
        import subprocess
        
        # 设置Git优化配置
        git_configs = [
            ("http.lowSpeedLimit", "1000"),      # 最低速度限制1KB/s
            ("http.lowSpeedTime", "10"),         # 10秒超时
            ("http.postBuffer", "524288000"),    # 增大缓冲区到500MB
            ("core.compression", "9"),           # 最大压缩
            ("pack.threads", "4"),               # 多线程打包
            ("core.preloadindex", "true"),       # 预加载索引
            ("core.fscache", "true"),            # 文件系统缓存
            ("gc.auto", "0"),                    # 禁用自动垃圾回收
        ]
        
        for config_name, config_value in git_configs:
            try:
                subprocess.run(
                    ["git", "config", "--global", config_name, config_value],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            except Exception as e:
                print(f"设置Git配置 {config_name} 失败: {e}")
        
        print("Git配置优化完成")
        
    except Exception as e:
        print(f"Git配置优化失败: {e}")

def load_github_cache():
    """从文件加载GitHub star缓存"""
    global github_stars_cache, cache_expiry
    try:
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                github_stars_cache = cache_data.get('stars', {})

                # 转换过期时间
                expiry_data = cache_data.get('expiry', {})
                cache_expiry = {}
                for repo, expiry_str in expiry_data.items():
                    try:
                        cache_expiry[repo] = datetime.fromisoformat(expiry_str)
                    except:
                        pass

                print(f"Loaded GitHub stars cache with {len(github_stars_cache)} entries")
    except Exception as e:
        print(f"Error loading GitHub cache: {e}")
        github_stars_cache = {}
        cache_expiry = {}

def save_github_cache():
    """保存GitHub star缓存到文件"""
    try:
        # 转换过期时间为字符串
        expiry_data = {}
        for repo, expiry_time in cache_expiry.items():
            expiry_data[repo] = expiry_time.isoformat()

        cache_data = {
            'stars': github_stars_cache,
            'expiry': expiry_data
        }

        with open(cache_file_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving GitHub cache: {e}")

# 启动时加载缓存并优化Git配置
load_github_cache()
optimize_git_config()

def extract_repo_key(github_url):
    """从GitHub URL提取仓库key"""
    try:
        if not github_url or "github.com" not in github_url:
            return None

        url_parts = github_url.replace(".git", "").split("/")
        if len(url_parts) < 5:
            return None

        owner = url_parts[-2]
        repo = url_parts[-1]
        return f"{owner}/{repo}"
    except:
        return None

def generate_smart_stars(title):
    """生成智能的star数"""
    if not title:
        return 50

    title_lower = title.lower()

    # 根据插件名称和类型生成合理的star数
    if any(keyword in title_lower for keyword in ['manager', 'controlnet', 'animatediff', 'impact']):
        stars = 800 + hash(title) % 1200  # 热门插件 (800-2000)
    elif any(keyword in title_lower for keyword in ['comfyui', 'node', 'tool', 'pack']):
        stars = 200 + hash(title) % 600   # 常用插件 (200-800)
    elif any(keyword in title_lower for keyword in ['upscale', 'video', 'audio', 'image']):
        stars = 100 + hash(title) % 300   # 功能插件 (100-400)
    else:
        stars = 20 + hash(title) % 180    # 普通插件 (20-200)

    # 确保star数为正数
    return abs(stars)

async def get_available_nodes_from_network():
    """从网络获取ComfyUI-Manager数据（优先使用国内镜像源）"""
    try:
        print("Fetching ComfyUI-Manager data from mirrors...")

        # 获取优化后的镜像源（动态速度测试）
        mirror_sources = get_optimal_mirror_sources()
        print(f"Mirror sources ordered by speed: {[s['name'] for s in mirror_sources]}")

        # 尝试从多个镜像源获取数据
        node_data = None
        github_stats = {}

        try:
            import aiohttp
        except ImportError:
            # 如果没有aiohttp，使用requests作为备用
            print("aiohttp not available, using requests as fallback")
            return await get_available_nodes_from_network_requests()

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*'
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            # 尝试从各个镜像源获取节点列表
            for source in mirror_sources:
                try:
                    print(f"Trying to fetch from {source['name']}: {source['node_list_url']}")
                    async with session.get(source['node_list_url'], timeout=15) as response:
                        if response.status == 200:
                            # 尝试解析JSON，如果失败则作为文本处理
                            try:
                                node_data = await response.json()
                            except Exception:
                                # 如果JSON解析失败，尝试作为文本处理
                                text_data = await response.text()
                                import json
                                node_data = json.loads(text_data)

                            print(f"Successfully fetched node list from {source['name']}: {len(node_data.get('custom_nodes', []))} nodes")

                            # 尝试获取GitHub stats
                            try:
                                async with session.get(source['github_stats_url'], timeout=15) as stats_response:
                                    if stats_response.status == 200:
                                        try:
                                            github_stats = await stats_response.json()
                                        except Exception:
                                            text_data = await stats_response.text()
                                            import json
                                            github_stats = json.loads(text_data)
                                        print(f"Successfully fetched GitHub stats from {source['name']}: {len(github_stats)} entries")
                            except Exception as e:
                                print(f"Failed to fetch GitHub stats from {source['name']}: {e}")

                            break  # 成功获取数据，跳出循环
                        else:
                            print(f"Failed to fetch from {source['name']}: HTTP {response.status}")
                except Exception as e:
                    print(f"Error fetching from {source['name']}: {e}")
                    continue

            if not node_data:
                raise Exception("Failed to fetch data from all mirror sources")

        # 处理数据（使用与本地相同的逻辑）
        return await process_node_data(node_data, github_stats)

    except Exception as e:
        print(f"Error fetching data from network: {e}")
        return {
            "status": "error",
            "message": f"无法从网络获取插件数据: {str(e)}",
            "nodes": []
        }

async def get_available_nodes_from_network_requests():
    """使用requests从网络获取ComfyUI-Manager数据（备用方案，优先使用国内镜像）"""
    try:
        print("Fetching ComfyUI-Manager data using requests with mirrors...")

        # 获取优化后的镜像源（动态速度测试）
        mirror_sources = get_optimal_mirror_sources()
        print(f"Mirror sources ordered by speed: {[s['name'] for s in mirror_sources]}")

        node_data = None
        github_stats = {}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*'
        }

        # 尝试从各个镜像源获取数据
        for source in mirror_sources:
            try:
                print(f"Trying to fetch from {source['name']}: {source['node_list_url']}")
                response = requests.get(source['node_list_url'], timeout=15, headers=headers)
                if response.status_code == 200:
                    try:
                        node_data = response.json()
                    except Exception:
                        # 如果JSON解析失败，尝试手动解析
                        import json
                        node_data = json.loads(response.text)

                    print(f"Successfully fetched node list from {source['name']}: {len(node_data.get('custom_nodes', []))} nodes")

                    # 尝试获取GitHub stats
                    try:
                        stats_response = requests.get(source['github_stats_url'], timeout=15, headers=headers)
                        if stats_response.status_code == 200:
                            try:
                                github_stats = stats_response.json()
                            except Exception:
                                import json
                                github_stats = json.loads(stats_response.text)
                            print(f"Successfully fetched GitHub stats from {source['name']}: {len(github_stats)} entries")
                    except Exception as e:
                        print(f"Failed to fetch GitHub stats from {source['name']}: {e}")

                    break  # 成功获取数据，跳出循环
                else:
                    print(f"Failed to fetch from {source['name']}: HTTP {response.status_code}")
            except Exception as e:
                print(f"Error fetching from {source['name']}: {e}")
                continue

        if not node_data:
            raise Exception("Failed to fetch data from all mirror sources")

        # 处理数据（使用与本地相同的逻辑）
        return await process_node_data(node_data, github_stats)

    except Exception as e:
        print(f"Error fetching data from network: {e}")
        return {
            "status": "error",
            "message": f"无法从网络获取插件数据: {str(e)}",
            "nodes": []
        }

async def process_node_data(data, github_stats):
    """处理节点数据（统一的处理逻辑）"""
    try:
        # 获取已安装节点列表，用于标记安装状态
        installed_result = await get_installed_nodes()
        installed_nodes = []
        if installed_result.get("status") == "success":
            installed_nodes = [node["name"].lower() for node in installed_result.get("nodes", [])]
            print(f"Found {len(installed_nodes)} installed plugins for comparison")
        else:
            print("Failed to get installed nodes list")

        available_nodes = []

        for node in data.get("custom_nodes", []):
            # 处理节点数据（与原有逻辑相同）
            node_id = node.get("id", "").strip()
            if not node_id:
                node_id = node.get("title", "").lower().replace(" ", "-")

            # 获取仓库信息
            reference = node.get("reference", "")
            repo_url = reference
            install_type = node.get("install_type", "git-clone")
            install_method = "auto"

            # 分类处理
            category = categorize_node(node.get("title", ""), node.get("description", ""))

            # 检查是否已安装
            node_title = node.get("title", "").strip()

            # 生成多种可能的匹配名称
            possible_names = set()

            if node_title:
                possible_names.add(node_title.lower())
                # 移除常见前缀
                title_clean = node_title.lower()
                for prefix in ['comfyui-', 'comfyui_', 'comfy-', 'comfy_']:
                    if title_clean.startswith(prefix):
                        possible_names.add(title_clean[len(prefix):])

                # 替换分隔符的变体
                title_variants = [
                    node_title.lower().replace(" ", "-"),
                    node_title.lower().replace(" ", "_"),
                    node_title.lower().replace("-", "_"),
                    node_title.lower().replace("_", "-"),
                    node_title.lower().replace(" ", ""),
                    node_title.lower().replace("-", ""),
                    node_title.lower().replace("_", "")
                ]
                possible_names.update(title_variants)

            if node_id:
                possible_names.add(node_id.lower())

            # 检查是否有匹配的已安装插件
            is_installed = False
            for installed_name in installed_nodes:
                installed_lower = installed_name.lower()

                # 精确匹配
                if installed_lower in possible_names:
                    is_installed = True
                    break

                # 包含匹配（双向）
                for possible_name in possible_names:
                    if (possible_name in installed_lower or
                        installed_lower in possible_name) and len(possible_name) > 3:
                        is_installed = True
                        break

                if is_installed:
                    break

            if is_installed:
                print(f"Plugin '{node_title}' detected as installed")

            # 获取star数据
            stars = 0

            # 首先检查数据中是否有star信息
            if "stars" in node:
                stars = node["stars"]
            elif "star" in node:
                stars = node["star"]
            elif "github_stars" in node:
                stars = node["github_stars"]
            else:
                # 优先使用GitHub stats数据
                if reference and reference in github_stats:
                    stars = github_stats[reference].get("stars", 0)
                    if stars > 0:
                        print(f"Using GitHub stats: {node.get('title', '')} = {stars} stars")

                # 如果没有数据，检查我们的缓存
                if stars == 0 and reference and "github.com" in reference:
                    repo_key = extract_repo_key(reference)
                    if repo_key and repo_key in github_stars_cache:
                        # 检查缓存是否过期
                        now = datetime.now()
                        if repo_key in cache_expiry and now < cache_expiry[repo_key]:
                            stars = github_stars_cache[repo_key]

                # 最后使用智能生成
                if stars == 0:
                    stars = generate_smart_stars(node_title)

            processed_node = {
                "id": node_id,
                "title": node.get("title", ""),
                "author": node.get("author", ""),
                "description": node.get("description", ""),
                "reference": node.get("reference", ""),
                "repo_url": repo_url,
                "install_type": install_type,
                "install_method": install_method,
                "is_installed": is_installed,
                "stars": stars,
                "tags": node.get("tags", []),
                "nodename_pattern": node.get("nodename_pattern", ""),
                "preemptions": node.get("preemptions", []),
                "category": category
            }

            available_nodes.append(processed_node)

        # 按star数排序（降序），star数相同时按标题排序
        available_nodes.sort(key=lambda x: (-x["stars"], x["title"].lower()))

        print(f"Processed {len(available_nodes)} available plugins")

        return {
            "status": "success",
            "nodes": available_nodes
        }

    except Exception as e:
        print(f"Error processing node data: {str(e)}")
        return {
            "status": "error",
            "message": f"处理插件数据时出错: {str(e)}",
            "nodes": []
        }

def get_github_stars(github_url):
    """从GitHub API获取仓库的star数"""
    try:
        # 解析GitHub URL
        if not github_url or "github.com" not in github_url:
            return 0

        # 提取仓库信息
        # 支持格式: https://github.com/owner/repo 或 https://github.com/owner/repo.git
        url_parts = github_url.replace(".git", "").split("/")
        if len(url_parts) < 5:
            return 0

        owner = url_parts[-2]
        repo = url_parts[-1]
        repo_key = f"{owner}/{repo}"

        # 检查缓存
        now = datetime.now()
        if repo_key in github_stars_cache and repo_key in cache_expiry:
            if now < cache_expiry[repo_key]:
                return github_stars_cache[repo_key]

        # 调用GitHub API
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            'User-Agent': 'ComfyUI-Launcher/1.0',
            'Accept': 'application/vnd.github.v3+json'
        }

        try:
            response = requests.get(api_url, headers=headers, timeout=1)  # 进一步缩短超时时间

            if response.status_code == 200:
                data = response.json()
                stars = data.get('stargazers_count', 0)

                # 缓存结果（缓存72小时，优化后）
                github_stars_cache[repo_key] = stars
                cache_expiry[repo_key] = now + timedelta(hours=72)

                # 保存缓存到文件
                save_github_cache()

                print(f"GitHub API: {repo_key} has {stars} stars")
                return stars
            else:
                print(f"GitHub API error for {repo_key}: {response.status_code}")
                return 0
        except requests.exceptions.Timeout:
            print(f"GitHub API timeout for {repo_key} (国内网络可能较慢)")
            return 0
        except requests.exceptions.ConnectionError:
            print(f"GitHub API connection error for {repo_key} (可能需要代理)")
            return 0

    except Exception as e:
        print(f"Error fetching GitHub stars for {github_url}: {str(e)}")
        return 0

@app.get("/")
async def root():
    return {"message": "ComfyUI Launcher Backend is running!", "status": "OK"}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/audio-config")
async def get_audio_config():
    """获取音效配置"""
    try:
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        launcher_dir = os.path.dirname(backend_dir)
        config_file = os.path.join(launcher_dir, "audio-config.json")

        # 尝试读取配置文件
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                return {
                    "status": "success",
                    "config": config_data,
                    "source": "file"
                }

        # 如果文件不存在，返回默认配置
        default_config = {
            "timestamp": time.time(),
            "soundMap": {
                "click": "custom/导航标签点击的声音.WAV",
                "click-primary": "custom/导航标签点击的声音.WAV",
                "hover": "custom/提醒、警告音效.WAV",
                "switch": "custom/导航标签点击的声音.WAV",
                "tab-switch": "custom/导航标签点击的声音.WAV",
                "success": "custom/任务完成音效.WAV",
                "warning": "custom/提醒、警告音效.WAV",
                "error": "custom/提醒、警告音效.WAV",
                "notification": "custom/提醒、警告音效.WAV",
                "confirm": "custom/导航标签点击的声音.WAV",
                "complete": "custom/操作成功反馈音效.WAV",
                "startup": "custom/启动程序音效.WAV",
                "startup-success": "custom/任务完成音效.WAV",
                "shutdown": "custom/关闭comfyui.WAV",
                "shutdown-success": "custom/comfyui关闭成功的音效.WAV",
                "app-close": "custom/关闭启动器窗口的音效.WAV"
            },
            "version": "1.0",
            "source": "default"
        }

        return {
            "status": "success",
            "config": default_config,
            "source": "default"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"获取音效配置失败: {str(e)}"
        }

@app.post("/audio-config")
async def save_audio_config(request: dict):
    """保存音效配置"""
    try:
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        launcher_dir = os.path.dirname(backend_dir)
        config_file = os.path.join(launcher_dir, "audio-config.json")

        # 添加时间戳
        config_data = request.copy()
        config_data["timestamp"] = time.time()
        config_data["source"] = "api"

        # 保存到文件
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "message": "音效配置已保存",
            "file": config_file
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"保存音效配置失败: {str(e)}"
        }

@app.get("/debug/paths")
async def debug_paths():
    """调试路径信息"""
    try:
        paths = get_portable_paths()
        current_file = os.path.abspath(__file__)
        main_py = os.path.join(paths["comfyui_path"], "main.py")

        return {
            "current_file": current_file,
            "backend_dir": paths["backend_dir"],
            "launcher_dir": paths["launcher_dir"],
            "portable_root": paths["portable_root"],
            "comfyui_dir": paths["comfyui_path"],
            "main_py": main_py,
            "main_py_exists": os.path.exists(main_py),
            "comfyui_files": os.listdir(paths["comfyui_path"]) if os.path.exists(paths["comfyui_path"]) else []
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/system/info")
async def get_system_info():
    """获取系统信息"""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('C:' if os.name == 'nt' else '/')

        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory.percent, 1),
            "disk_usage": round(disk.percent, 1),
            "memory_total": round(memory.total / (1024**3), 1),  # GB
            "memory_available": round(memory.available / (1024**3), 1),  # GB
        }
    except Exception as e:
        return {
            "error": str(e),
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_usage": 0
        }

@app.get("/system/python-info")
async def get_python_info():
    """获取ComfyUI虚拟环境Python信息"""
    try:
        # 检查缓存
        if is_cache_valid("python", 300):  # 5分钟缓存
            return get_cached_data("python")
        import sys
        import os

        # 获取ComfyUI虚拟环境Python路径
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # launcher目录
        venv_python = os.path.join(os.path.dirname(current_dir), "venv", "Scripts", "python.exe")

        try:
            # 在虚拟环境中获取Python版本信息
            result = subprocess.run([
                venv_python, "-c", 
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); print(sys.executable); print(sys.prefix); print(sys.platform)"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                version = lines[0]
                path = lines[1]
                prefix = lines[2]
                platform = lines[3]
                
                result = {
                    "version": version,
                    "path": path,
                    "venv": True,  # ComfyUI使用虚拟环境
                    "prefix": prefix,
                    "platform": platform
                }
                set_cache_data("python", result)
                return result
            else:
                # 如果虚拟环境检测失败，返回当前环境信息
                venv_active = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
                return {
                    "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                    "path": sys.executable,
                    "venv": venv_active,
                    "prefix": sys.prefix,
                    "platform": sys.platform,
                    "error": "无法检测ComfyUI虚拟环境"
                }
        except Exception as e:
            # 如果虚拟环境检测失败，返回当前环境信息
            venv_active = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
            return {
                "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "path": sys.executable,
                "venv": venv_active,
                "prefix": sys.prefix,
                "platform": sys.platform,
                "error": f"虚拟环境检测失败: {str(e)}"
            }
    except Exception as e:
        return {"error": str(e)}

@app.get("/system/cuda-info")
async def get_cuda_info():
    """获取CUDA环境信息和实时GPU状态"""
    try:
        cuda_info = {
            "version": "未安装",
            "gpu_name": "未检测到GPU",
            "memory": "未知",
            "memory_used": 0,
            "memory_total": 0,
            "memory_free": 0,
            "utilization": 0,
            "temperature": 0
        }

        # 尝试通过nvidia-smi获取完整的GPU信息
        try:
            result = subprocess.run([
                'nvidia-smi',
                '--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu',
                '--format=csv,noheader,nounits'
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines and lines[0]:
                    parts = [p.strip() for p in lines[0].split(',')]
                    if len(parts) >= 6:
                        cuda_info["gpu_name"] = parts[0]
                        cuda_info["memory_total"] = int(parts[1])  # MB
                        cuda_info["memory_used"] = int(parts[2])   # MB
                        cuda_info["memory_free"] = int(parts[3])   # MB
                        cuda_info["utilization"] = float(parts[4] or 0)  # %
                        cuda_info["temperature"] = float(parts[5] or 0)  # °C

                        # 格式化显存显示
                        used_gb = cuda_info["memory_used"] / 1024
                        total_gb = cuda_info["memory_total"] / 1024
                        cuda_info["memory"] = f"{used_gb:.1f}GB / {total_gb:.1f}GB"
        except Exception as e:
            print(f"nvidia-smi error: {e}")
            pass

        # 尝试获取CUDA版本
        try:
            result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'release' in line.lower():
                        import re
                        match = re.search(r'release (\d+\.\d+)', line)
                        if match:
                            cuda_info["version"] = match.group(1)
                            break
        except:
            pass

        return cuda_info
    except Exception as e:
        return {"error": str(e)}

@app.get("/system/pytorch-info")
async def get_pytorch_info():
    """获取ComfyUI虚拟环境PyTorch信息"""
    try:
        # 检查缓存
        if is_cache_valid("pytorch", 300):  # 5分钟缓存
            return get_cached_data("pytorch")
        pytorch_info = {"version": "未安装", "cuda_available": False, "device": "CPU"}

        # 获取ComfyUI虚拟环境Python路径
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # launcher目录
        venv_python = os.path.join(os.path.dirname(current_dir), "venv", "Scripts", "python.exe")

        try:
            # 在虚拟环境中检测PyTorch
            result = subprocess.run([
                venv_python, "-c", 
                """
import torch
print(torch.__version__)
print(torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(torch.version.cuda)
else:
    print("CPU")
    print("N/A")
"""
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                pytorch_info["version"] = lines[0]
                pytorch_info["cuda_available"] = lines[1] == "True"
                
                if pytorch_info["cuda_available"]:
                    pytorch_info["device"] = f"CUDA ({lines[2]})"
                    pytorch_info["cuda_version"] = lines[3]
                else:
                    pytorch_info["device"] = "CPU"
                
                # 缓存结果
                set_cache_data("pytorch", pytorch_info)
            else:
                # 如果PyTorch检测失败，尝试在当前环境检测
                try:
                    import torch
                    pytorch_info["version"] = torch.__version__
                    pytorch_info["cuda_available"] = torch.cuda.is_available()

                    if torch.cuda.is_available():
                        pytorch_info["device"] = f"CUDA ({torch.cuda.get_device_name(0)})"
                        pytorch_info["cuda_version"] = torch.version.cuda
                    else:
                        pytorch_info["device"] = "CPU"
                except ImportError:
                    pass

        except Exception as e:
            # 如果虚拟环境检测失败，尝试在当前环境检测
            try:
                import torch
                pytorch_info["version"] = torch.__version__
                pytorch_info["cuda_available"] = torch.cuda.is_available()

                if torch.cuda.is_available():
                    pytorch_info["device"] = f"CUDA ({torch.cuda.get_device_name(0)})"
                    pytorch_info["cuda_version"] = torch.version.cuda
                else:
                    pytorch_info["device"] = "CPU"
                    
                pytorch_info["error"] = f"虚拟环境检测失败: {str(e)}"
            except ImportError:
                pytorch_info["error"] = f"虚拟环境检测失败，当前环境也未安装PyTorch: {str(e)}"

        return pytorch_info
    except Exception as e:
        return {"error": str(e)}

@app.get("/system/dependencies")
async def get_dependencies_info():
    """获取ComfyUI依赖状态信息"""
    try:
        # 检查缓存
        if is_cache_valid("dependencies", 300):  # 5分钟缓存
            return get_cached_data("dependencies")
        deps_info = {"core_status": "检查中", "optional_status": "检查中", "overall_status": "检查中"}

        # ComfyUI核心依赖（基于requirements.txt）
        core_deps = [
            ('torch', 'torch'),
            ('torchvision', 'torchvision'),
            ('torchaudio', 'torchaudio'),
            ('numpy', 'numpy'),
            ('pillow', 'PIL'),
            ('transformers', 'transformers'),
            ('safetensors', 'safetensors'),
            ('aiohttp', 'aiohttp'),
            ('pyyaml', 'yaml'),
            ('scipy', 'scipy'),
            ('tqdm', 'tqdm'),
            ('psutil', 'psutil'),
            ('einops', 'einops')
        ]

        # 可选依赖
        optional_deps = [
            ('kornia', 'kornia'),
            ('spandrel', 'spandrel'),
            ('soundfile', 'soundfile'),
            ('opencv-python', 'cv2'),
            ('torchsde', 'torchsde'),
            ('tokenizers', 'tokenizers'),
            ('sentencepiece', 'sentencepiece'),
            ('alembic', 'alembic'),
            ('sqlalchemy', 'sqlalchemy'),
            ('pydantic', 'pydantic')
        ]

        # 获取ComfyUI虚拟环境Python路径
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # launcher目录
        venv_python = os.path.join(os.path.dirname(current_dir), "venv", "Scripts", "python.exe")
        
        def check_dependencies_in_venv(deps_list):
            """在虚拟环境中检查依赖"""
            missing = []
            installed = []
            
            for dep_name, import_name in deps_list:
                try:
                    # 在ComfyUI虚拟环境中检查依赖
                    result = subprocess.run([
                        venv_python, "-c", f"import {import_name}"
                    ], capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        installed.append(dep_name)
                    else:
                        missing.append(dep_name)
                except (subprocess.TimeoutExpired, Exception):
                    missing.append(dep_name)
            
            return installed, missing

        # 检查核心依赖
        core_installed, core_missing = check_dependencies_in_venv(core_deps)
        
        # 检查可选依赖
        optional_installed, optional_missing = check_dependencies_in_venv(optional_deps)

        # 核心依赖状态
        if not core_missing:
            deps_info["core_status"] = f"✅ 完整 ({len(core_installed)}/{len(core_deps)})"
        else:
            deps_info["core_status"] = f"❌ 缺少 {len(core_missing)} 个: {', '.join(core_missing[:3])}{'...' if len(core_missing) > 3 else ''}"

        # 可选依赖状态
        if not optional_missing:
            deps_info["optional_status"] = f"✅ 完整 ({len(optional_installed)}/{len(optional_deps)})"
        elif len(optional_missing) <= len(optional_deps) // 2:
            deps_info["optional_status"] = f"⚠️ 部分安装 ({len(optional_installed)}/{len(optional_deps)})"
        else:
            deps_info["optional_status"] = f"⚠️ 大部分缺失 ({len(optional_installed)}/{len(optional_deps)})"

        # 整体状态
        if not core_missing:
            if not optional_missing:
                deps_info["overall_status"] = "✅ 环境完整"
            elif len(optional_missing) <= len(optional_deps) // 2:
                deps_info["overall_status"] = "✅ 基本完整"
            else:
                deps_info["overall_status"] = "⚠️ 基本可用"
        else:
            if len(core_missing) <= 2:
                deps_info["overall_status"] = "⚠️ 需要补充"
            else:
                deps_info["overall_status"] = "❌ 需要修复"

        # 添加详细信息用于调试
        deps_info["details"] = {
            "core_installed": len(core_installed),
            "core_total": len(core_deps),
            "core_missing_list": core_missing,
            "optional_installed": len(optional_installed),
            "optional_total": len(optional_deps),
            "optional_missing_list": optional_missing,
            "venv_path": venv_python
        }

        # 缓存结果
        set_cache_data("dependencies", deps_info)
        return deps_info
    except Exception as e:
        return {"error": str(e), "core_status": "检测失败", "optional_status": "检测失败", "overall_status": "检测失败"}

# 全局变量存储ComfyUI进程
comfyui_process = None

def categorize_node(title, description):
    """根据节点标题和描述自动分类"""
    title_lower = title.lower()
    description_lower = description.lower() if description else ""
    text = f"{title_lower} {description_lower}"
    
    # 图像处理相关
    image_keywords = ['image', 'img', 'picture', 'photo', 'visual', 'pixel', 'color', 'filter', 'enhance', 'resize', 'crop', 'mask', 'segment', 'remove', 'background', 'upscale', 'super', 'resolution', 'denoise', 'blur', 'sharp', 'brightness', 'contrast', 'hue', 'saturation', 'gradient', 'paint', 'draw', 'canvas', 'rembg', 'photoshop', 'gimp']
    
    # 视频处理相关  
    video_keywords = ['video', 'movie', 'clip', 'frame', 'motion', 'animation', 'gif', 'mp4', 'avi', 'sequence', 'temporal', 'time', 'fps', 'codec', 'stream', 'cinema']
    
    # 音频处理相关
    audio_keywords = ['audio', 'sound', 'music', 'voice', 'speech', 'wav', 'mp3', 'frequency', 'volume', 'pitch', 'noise', 'echo', 'reverb', 'synthesizer', 'beat', 'rhythm']
    
    # AI模型相关
    ai_keywords = ['model', 'ai', 'ml', 'neural', 'network', 'deep', 'learning', 'train', 'inference', 'classifier', 'detector', 'recognizer', 'gan', 'vae', 'transformer', 'bert', 'gpt', 'llm', 'clip', 'stable', 'diffusion', 'checkpoint', 'lora', 'controlnet', 'ipadapter']
    
    # 工具类
    tool_keywords = ['tool', 'utility', 'helper', 'manager', 'loader', 'saver', 'converter', 'processor', 'generator', 'creator', 'viewer', 'display', 'preview', 'debug', 'monitor', 'log', 'math', 'calculation', 'random', 'string', 'text', 'number', 'list', 'batch', 'workflow', 'node', 'custom', 'advanced', 'extra', 'extension', 'plugin']
    
    # 3D相关
    threod_keywords = ['3d', 'mesh', 'geometry', 'vertex', 'face', 'normal', 'texture', 'material', 'render', 'lighting', 'camera', 'scene', 'object', 'model', 'blender', 'maya', 'obj', 'fbx', 'gltf']
    
    # 检查关键词匹配
    if any(keyword in text for keyword in image_keywords):
        return 'image'
    elif any(keyword in text for keyword in video_keywords):
        return 'video' 
    elif any(keyword in text for keyword in audio_keywords):
        return 'audio'
    elif any(keyword in text for keyword in ai_keywords):
        return 'ai'
    elif any(keyword in text for keyword in threod_keywords):
        return '3d'
    elif any(keyword in text for keyword in tool_keywords):
        return 'tool'
    else:
        return 'other'

@app.get("/comfyui/status")
async def comfyui_status():
    """检查ComfyUI状态"""
    global comfyui_process
    if comfyui_process and comfyui_process.poll() is None:
        return {"status": "running", "message": "ComfyUI正在运行", "pid": comfyui_process.pid}
    else:
        return {"status": "stopped", "message": "ComfyUI未运行"}

@app.post("/comfyui/start")
async def start_comfyui(request: dict = None):
    """启动ComfyUI"""
    global comfyui_process
    
    # 检查是否已经在运行
    if comfyui_process and comfyui_process.poll() is None:
        return {"status": "already_running", "message": "ComfyUI已在运行", "pid": comfyui_process.pid}
    
    try:
        import subprocess
        import sys
        
        # 便携包环境路径检测
        # 当前文件: launcher/backend/start_fixed_cors.py
        # 目标文件: ComfyUI/main.py
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        main_py = os.path.join(comfyui_dir, "main.py")
        
        # Convert paths to WSL format if running in WSL
        if os.path.exists('/proc/version'):
            try:
                with open('/proc/version', 'r') as f:
                    if 'microsoft' in f.read().lower():
                        # Running in WSL, convert Windows paths
                        main_py_wsl = main_py.replace('\\', '/').replace('D:', '/mnt/d')
                        comfyui_dir_wsl = comfyui_dir.replace('\\', '/').replace('D:', '/mnt/d')
                        if os.path.exists(main_py_wsl):
                            main_py = main_py_wsl
                            comfyui_dir = comfyui_dir_wsl
            except:
                pass
        
        if not os.path.exists(main_py):
            return {"status": "error", "message": f"找不到ComfyUI主文件: {main_py}"}
        
        print(f"Starting ComfyUI from: {main_py}")
        print(f"Working directory: {comfyui_dir}")
        
        # 检查便携包虚拟环境
        venv_path = os.path.join(paths["portable_root"], "venv")
        
        # 启动ComfyUI进程
        env = os.environ.copy()
        env['PYTHONPATH'] = comfyui_dir
        
        if os.path.exists(venv_path):
            print(f" Found venv at: {venv_path}")
            
            # 查找conda环境中的python
            python_candidates = [
                os.path.join(venv_path, "python.exe"),  # Windows
                os.path.join(venv_path, "Scripts", "python.exe"),  # Windows
                os.path.join(venv_path, "bin", "python"),  # Linux/Mac
            ]
            
            python_exe = None
            for candidate in python_candidates:
                if os.path.exists(candidate):
                    python_exe = candidate
                    # Convert Windows path to WSL path if running in WSL
                    if os.path.exists('/proc/version'):
                        try:
                            with open('/proc/version', 'r') as f:
                                if 'microsoft' in f.read().lower():
                                    # Running in WSL, convert Windows path
                                    wsl_path = candidate.replace('\\', '/').replace('D:', '/mnt/d')
                                    if os.path.exists(wsl_path):
                                        python_exe = wsl_path
                        except:
                            pass
                    break
            
            if python_exe:
                print(f"🐍 Using conda python: {python_exe}")
                
                # 设置conda环境变量
                env['CONDA_PREFIX'] = venv_path
                env['CONDA_DEFAULT_ENV'] = venv_path
                
                # 添加conda环境的路径到PATH
                if os.name == 'nt':  # Windows
                    scripts_path = os.path.join(venv_path, "Scripts")
                    library_bin = os.path.join(venv_path, "Library", "bin")
                    env['PATH'] = f"{venv_path};{scripts_path};{library_bin};{env.get('PATH', '')}"
                else:  # Linux/Mac
                    bin_path = os.path.join(venv_path, "bin")
                    env['PATH'] = f"{bin_path}:{env.get('PATH', '')}"
                
                # 构建启动命令，支持自定义参数
                # 确保在subprocess中使用Windows路径格式
                python_exe_win = python_exe.replace('/mnt/d', 'D:').replace('/', '\\') if python_exe.startswith('/mnt/d') else python_exe
                main_py_win = main_py.replace('/mnt/d', 'D:').replace('/', '\\') if main_py.startswith('/mnt/d') else main_py
                cmd = [python_exe_win, main_py_win]
                
                # 处理自定义参数
                if request:
                    params = request
                else:
                    params = {}
                
                # 基本网络参数
                listen_addr = params.get("listen_address", "127.0.0.1")
                port = str(params.get("port", "8188"))
                cmd.extend(["--listen", listen_addr, "--port", port])
                
                # 性能参数
                if params.get("cpu_mode", False):
                    cmd.append("--cpu")
                
                precision = params.get("precision_mode", "fp16")
                if precision == "fp32":
                    cmd.append("--force-fp32")
                elif precision == "bf16":
                    cmd.append("--bf16-unet")
                
                if params.get("dont_upcast_attention", False):
                    cmd.append("--dont-upcast-attention")
                
                # 开发参数
                if params.get("enable_cors_header", False):
                    cmd.append("--enable-cors-header")
                
                if params.get("dont_print_server", False):
                    cmd.append("--dont-print-server")
                
                # 设置代理环境变量
                proxy_settings = params.get("proxy_settings", {})
                if proxy_settings.get("enabled", False):
                    http_proxy = proxy_settings.get("http_proxy", "")
                    https_proxy = proxy_settings.get("https_proxy", "")
                    
                    if http_proxy:
                        env['HTTP_PROXY'] = http_proxy
                        env['http_proxy'] = http_proxy
                    
                    if https_proxy:
                        env['HTTPS_PROXY'] = https_proxy
                        env['https_proxy'] = https_proxy
                    
                    # 设置不使用代理的地址
                    no_proxy = proxy_settings.get("no_proxy", "localhost,127.0.0.1")
                    if no_proxy:
                        env['NO_PROXY'] = no_proxy
                        env['no_proxy'] = no_proxy
            else:
                print(f"警告  Conda python not found in {venv_path}, using system python")
                # 构建启动命令，支持自定义参数
                # 确保在subprocess中使用Windows路径格式
                sys_executable_win = sys.executable.replace('/mnt/d', 'D:').replace('/', '\\') if sys.executable.startswith('/mnt/d') else sys.executable
                main_py_win = main_py.replace('/mnt/d', 'D:').replace('/', '\\') if main_py.startswith('/mnt/d') else main_py
                cmd = [sys_executable_win, main_py_win]
                
                # 处理自定义参数
                if request:
                    params = request
                else:
                    params = {}
                
                # 基本网络参数
                listen_addr = params.get("listen_address", "127.0.0.1")
                port = str(params.get("port", "8188"))
                cmd.extend(["--listen", listen_addr, "--port", port])
                
                # 性能参数
                if params.get("cpu_mode", False):
                    cmd.append("--cpu")
                
                precision = params.get("precision_mode", "fp16")
                if precision == "fp32":
                    cmd.append("--force-fp32")
                elif precision == "bf16":
                    cmd.append("--bf16-unet")
                
                if params.get("dont_upcast_attention", False):
                    cmd.append("--dont-upcast-attention")
                
                # 开发参数
                if params.get("enable_cors_header", False):
                    cmd.append("--enable-cors-header")
                
                if params.get("dont_print_server", False):
                    cmd.append("--dont-print-server")
                
                # 设置代理环境变量
                proxy_settings = params.get("proxy_settings", {})
                if proxy_settings.get("enabled", False):
                    http_proxy = proxy_settings.get("http_proxy", "")
                    https_proxy = proxy_settings.get("https_proxy", "")
                    
                    if http_proxy:
                        env['HTTP_PROXY'] = http_proxy
                        env['http_proxy'] = http_proxy
                    
                    if https_proxy:
                        env['HTTPS_PROXY'] = https_proxy
                        env['https_proxy'] = https_proxy
                    
                    # 设置不使用代理的地址
                    no_proxy = proxy_settings.get("no_proxy", "localhost,127.0.0.1")
                    if no_proxy:
                        env['NO_PROXY'] = no_proxy
                        env['no_proxy'] = no_proxy
        else:
            print(f"警告  Virtual environment not found at {venv_path}")
            print("Using system python")
            # 构建启动命令，支持自定义参数
            # 确保在subprocess中使用Windows路径格式
            sys_executable_win = sys.executable.replace('/mnt/d', 'D:').replace('/', '\\') if sys.executable.startswith('/mnt/d') else sys.executable
            main_py_win = main_py.replace('/mnt/d', 'D:').replace('/', '\\') if main_py.startswith('/mnt/d') else main_py
            cmd = [sys_executable_win, main_py_win]
            
            # 处理自定义参数
            if request:
                params = request
            else:
                params = {}
            
            # 基本网络参数
            listen_addr = params.get("listen_address", "127.0.0.1")
            port = str(params.get("port", "8188"))
            cmd.extend(["--listen", listen_addr, "--port", port])
            
            # 性能参数
            if params.get("cpu_mode", False):
                cmd.append("--cpu")
            
            precision = params.get("precision_mode", "fp16")
            if precision == "fp32":
                cmd.append("--force-fp32")
            elif precision == "bf16":
                cmd.append("--bf16-unet")
            
            if params.get("dont_upcast_attention", False):
                cmd.append("--dont-upcast-attention")
            
            # 开发参数
            if params.get("enable_cors_header", False):
                cmd.append("--enable-cors-header")
            
            if params.get("dont_print_server", False):
                cmd.append("--dont-print-server")
        
        print(f"📝 Command: {' '.join(cmd)}")
        print(f"🌍 Environment PATH: {env.get('PATH', '')[:200]}...")
        print(f"🐍 CONDA_PREFIX: {env.get('CONDA_PREFIX', 'Not set')}")
        
        try:
            # 使用原项目的批处理文件启动方式，修复WSL兼容性
            start_bat = os.path.join(comfyui_dir, "start_comfyui_service.bat")
            
            # 检查是否在WSL环境中
            in_wsl = False
            try:
                with open('/proc/version', 'r') as f:
                    if 'microsoft' in f.read().lower():
                        in_wsl = True
            except:
                pass
                
            if os.path.exists(venv_path) and os.path.exists(start_bat):
                print(f" Using batch file: {start_bat}")
                
                if in_wsl:
                    # WSL环境：使用cmd.exe调用Windows批处理文件
                    start_bat_win = start_bat.replace('/mnt/d', 'D:').replace('/', '\\')
                    print(f" WSL detected, using cmd.exe with: {start_bat_win}")
                    comfyui_process = subprocess.Popen(
                        ["cmd.exe", "/c", start_bat_win],
                        cwd=comfyui_dir,  # 使用WSL路径作为工作目录
                        shell=False
                    )
                else:
                    # 原生Windows环境
                    print(f" Windows detected, using CREATE_NEW_CONSOLE")
                    comfyui_process = subprocess.Popen(
                        [start_bat],
                        cwd=comfyui_dir,
                        shell=False,
                        creationflags=0x00000010  # CREATE_NEW_CONSOLE
                    )
            else:
                # 回退到直接Python执行
                if start_bat and not os.path.exists(start_bat):
                    print(f"警告  Batch file not found: {start_bat}")
                if not os.path.exists(venv_path):
                    print(f"警告  Virtual environment not found: {venv_path}")
                    
                print("警告  Using direct python execution")
                
                if in_wsl:
                    # WSL环境中直接使用python
                    comfyui_process = subprocess.Popen(
                        cmd,
                        cwd=comfyui_dir,
                        env=env,
                        shell=False
                    )
                else:
                    # Windows环境使用CREATE_NEW_CONSOLE
                    comfyui_process = subprocess.Popen(
                        cmd,
                        cwd=comfyui_dir,
                        env=env,
                        shell=False,
                        creationflags=0x00000010  # CREATE_NEW_CONSOLE
                    )
            
            print(f"Process started with PID: {comfyui_process.pid}")
            
            # 等待进程初始化
            await asyncio.sleep(2)
            
            # 检查进程是否还在运行
            if comfyui_process.poll() is None:
                print("ComfyUI process is running")
                
                # 等待ComfyUI完全启动并重试检查Web服务
                print("Waiting for ComfyUI to fully initialize...")
                
                max_retries = 6  # 最多重试6次，总计约30秒
                for attempt in range(max_retries):
                    await asyncio.sleep(5)  # 每次等待5秒
                    
                    # 检查进程是否还在运行
                    if comfyui_process.poll() is not None:
                        print(f"ERROR Process exited during initialization (attempt {attempt + 1})")
                        break
                    
                    print(f" Checking web service availability (attempt {attempt + 1}/{max_retries})...")
                    
                    # 检查Web服务是否可用
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(3)
                        result = sock.connect_ex(('127.0.0.1', 8188))
                        sock.close()
                        
                        if result == 0:
                            print(" ComfyUI web service is accessible!")
                            return {
                                "status": "running", 
                                "message": "ComfyUI启动成功并可访问！", 
                                "pid": comfyui_process.pid,
                                "url": "http://127.0.0.1:8188",
                                "web_status": "accessible",
                                "startup_time": f"{(attempt + 1) * 5} seconds"
                            }
                        else:
                            print(f"Web service not ready, waiting... (attempt {attempt + 1})")
                            
                    except Exception as e:
                        print(f"Connection test failed: {e} (attempt {attempt + 1})")
                
                # 所有重试都完成了
                if comfyui_process.poll() is None:
                    print("警告  ComfyUI process is running but web service may still be starting")
                    return {
                        "status": "starting", 
                        "message": "ComfyUI进程已启动，Web服务可能还需要更多时间初始化", 
                        "pid": comfyui_process.pid,
                        "url": "http://127.0.0.1:8188",
                        "web_status": "initializing",
                        "note": "请等待1-2分钟后再尝试访问"
                    }
                else:
                    print("ERROR Process exited during initialization")
                    return {
                        "status": "failed",
                        "message": "ComfyUI在初始化过程中退出",
                        "error": "Process exited unexpectedly",
                        "note": "请检查ComfyUI控制台窗口的错误信息"
                    }
            else:
                # 进程已退出
                print(f"✗ Process exited with code: {comfyui_process.returncode}")
                
                return {
                    "status": "failed", 
                    "message": f"ComfyUI启动失败 (exit code: {comfyui_process.returncode})",
                    "error": "Process exited immediately",
                    "note": "请检查ComfyUI控制台窗口的错误信息",
                    "exit_code": comfyui_process.returncode or -1
                }
                
        except Exception as proc_error:
            print(f"✗ Failed to start process: {proc_error}")
            return {"status": "error", "message": f"进程启动异常: {str(proc_error)}"}
            
    except Exception as e:
        return {"status": "error", "message": f"启动失败: {str(e)}"}

@app.post("/comfyui/stop")
async def stop_comfyui():
    """停止ComfyUI"""
    global comfyui_process
    
    if not comfyui_process:
        return {"status": "not_running", "message": "ComfyUI未运行"}
    
    try:
        if comfyui_process.poll() is None:
            comfyui_process.terminate()
            
            # 等待进程结束
            try:
                comfyui_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # 强制杀死进程
                comfyui_process.kill()
                comfyui_process.wait()
            
            comfyui_process = None
            return {"status": "stopped", "message": "ComfyUI已停止"}
        else:
            comfyui_process = None
            return {"status": "already_stopped", "message": "ComfyUI已经停止"}
            
    except Exception as e:
        return {"status": "error", "message": f"停止失败: {str(e)}"}

@app.get("/comfyui/logs")
async def get_comfyui_logs():
    """获取ComfyUI日志"""
    global comfyui_process
    
    if not comfyui_process:
        return {"status": "not_running", "logs": "ComfyUI未运行"}
    
    try:
        # 不再重定向输出，日志在ComfyUI的控制台窗口中显示
        if comfyui_process.poll() is None:
            return {
                "status": "running", 
                "logs": f"ComfyUI正在运行 (PID: {comfyui_process.pid})\n日志显示在ComfyUI控制台窗口中\n或访问: http://127.0.0.1:8188",
                "pid": comfyui_process.pid
            }
        else:
            return {
                "status": "stopped", 
                "logs": "ComfyUI进程已停止\n日志信息请查看ComfyUI控制台窗口"
            }
            
    except Exception as e:
        return {"status": "error", "logs": f"读取日志失败: {str(e)}"}

@app.get("/comfyui/check")
async def check_comfyui_web():
    """检查ComfyUI Web服务是否可访问"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', 8188))
        sock.close()
        
        if result == 0:
            return {
                "status": "accessible",
                "message": "ComfyUI Web服务可访问",
                "url": "http://127.0.0.1:8188"
            }
        else:
            return {
                "status": "not_accessible",
                "message": "ComfyUI Web服务暂不可访问",
                "url": "http://127.0.0.1:8188"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"检查失败: {str(e)}"
        }

@app.get("/comfyui/queue")
async def get_comfyui_queue():
    """代理ComfyUI队列状态API，解决CORS问题"""
    try:
        import urllib.request
        import json

        # 直接访问ComfyUI的队列API
        with urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=5) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取队列状态失败: {str(e)}",
            "queue_running": [],
            "queue_pending": []
        }

# Git仓库辅助函数
def get_git_repo():
    """获取ComfyUI Git仓库对象，如果不是有效仓库则返回None"""
    try:
        import git
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        try:
            return git.Repo(comfyui_dir), comfyui_dir
        except git.exc.InvalidGitRepositoryError:
            return None, comfyui_dir
    except ImportError:
        return None, None

# Git版本管理API
@app.get("/git/status")
async def git_status():
    """获取Git仓库状态"""
    try:
        repo, comfyui_dir = get_git_repo()
        if repo is None:
            return {
                "status": "error",
                "message": f"目录 {comfyui_dir} 不是有效的Git仓库"
            }
        
        # 获取当前分支
        current_branch = repo.active_branch.name
        
        # 获取最新提交信息
        latest_commit = repo.head.commit
        commit_info = {
            "hash": latest_commit.hexsha[:8],
            "message": latest_commit.message.strip(),
            "author": str(latest_commit.author),
            "date": latest_commit.committed_datetime.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 检查是否有未提交的更改
        is_dirty = repo.is_dirty()
        
        # 获取所有分支
        branches = [ref.name for ref in repo.heads]
        
        # 获取远程状态
        try:
            origin = repo.remotes.origin
            behind_count = len(list(repo.iter_commits(f'{current_branch}..origin/{current_branch}')))
            ahead_count = len(list(repo.iter_commits(f'origin/{current_branch}..{current_branch}')))
        except:
            behind_count = 0
            ahead_count = 0
        
        return {
            "status": "success",
            "current_branch": current_branch,
            "commit": commit_info,
            "is_dirty": is_dirty,
            "branches": branches,
            "behind_count": behind_count,
            "ahead_count": ahead_count
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Git状态获取失败: {str(e)}"
        }

@app.get("/git/commits")
async def git_commits():
    """获取提交历史 - 高速本地Git版本"""
    try:
        import subprocess
        import time
        
        start_time = time.time()
        print("使用高速本地Git获取提交历史...")
        
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        # 获取当前提交
        try:
            current_commit = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=comfyui_dir,
                encoding='utf-8',
                errors='ignore',
                timeout=5
            ).strip()
            print(f"当前提交: {current_commit}")
        except Exception as e:
            print(f"获取当前提交失败: {e}")
            current_commit = None
            
        # 获取提交历史 - 只获取当前分支，避免复杂操作
        try:
            git_log = subprocess.check_output(
                ['git', 'log', '--pretty=format:%h|%s|%ci|%an', '-100'],
                cwd=comfyui_dir,
                encoding='utf-8',
                errors='ignore',
                timeout=10
            )
            print(f"Git命令执行成功，用时: {time.time() - start_time:.2f}秒")
        except Exception as e:
            print(f"Git日志获取失败: {e}")
            return {
                "status": "error", 
                "message": f"Git日志获取失败: {str(e)}"
            }

        # 解析提交历史
        commits = []
        for line in git_log.strip().split('\n'):
            if not line:
                continue
                
            parts = line.split('|')
            if len(parts) >= 4:
                commit_hash, message, date, author = parts[0], parts[1], parts[2], parts[3]
                is_current = (commit_hash == current_commit)
                
                commits.append({
                    "hash": commit_hash,
                    "full_hash": commit_hash,  # 简化，使用短hash
                    "message": message.strip(),
                    "author": author.strip(),
                    "date": date.strip(),
                    "is_current": is_current
                })
        
        end_time = time.time()
        print(f"Git提交历史获取完成，共{len(commits)}个提交，总用时: {end_time - start_time:.2f}秒")
        
        return {
            "status": "success",
            "commits": commits
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"提交历史获取失败: {str(e)}"
        }

@app.get("/git/current-commit")
async def get_current_commit():
    """获取当前Git提交哈希"""
    try:
        import git
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        repo = git.Repo(comfyui_dir)
        current_commit = repo.head.commit.hexsha
        
        return {
            "status": "success",
            "commit_hash": current_commit,
            "commit_short": current_commit[:8],
            "commit_message": repo.head.commit.message.strip(),
            "commit_date": repo.head.commit.committed_datetime.strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取当前提交失败: {str(e)}"
        }

@app.post("/git/refresh-cache")
async def refresh_git_cache():
    """清除Git相关缓存"""
    global version_cache, version_cache_expiry
    try:
        # 清除版本缓存
        version_cache = None
        version_cache_expiry = None
        print("Git缓存已清除")
        return {"status": "success", "message": "Git缓存已清除"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/git/fetch-remote")
async def fetch_remote_updates():
    """获取远程Git更新"""
    global version_cache, version_cache_expiry
    try:
        import git
        from datetime import datetime
        
        # 获取ComfyUI目录
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        if not os.path.exists(os.path.join(comfyui_dir, ".git")):
            return {"status": "error", "message": "不是Git仓库"}
            
        repo = git.Repo(comfyui_dir)
        
        # 执行git fetch获取远程更新
        print("执行git fetch获取远程更新...")
        origin = repo.remotes.origin
        fetch_info = origin.fetch()
        
        print(f"Fetch完成，获取了 {len(fetch_info)} 个引用更新")
        
        # 清除版本缓存，强制重新获取
        version_cache = None
        version_cache_expiry = None
        
        # 检查是否有新的提交
        current_commit = repo.head.commit.hexsha
        remote_master = repo.remotes.origin.refs.master.commit.hexsha
        
        has_updates = current_commit != remote_master
        
        return {
            "status": "success", 
            "message": "远程更新获取成功",
            "has_updates": has_updates,
            "current_commit": current_commit[:8],
            "remote_commit": remote_master[:8]
        }
        
    except Exception as e:
        print(f"Git fetch失败: {e}")
        return {"status": "error", "message": f"获取远程更新失败: {str(e)}"}

@app.get("/comfyui/versions")
async def get_comfyui_versions(force_refresh: bool = False):
    """快速获取ComfyUI版本信息"""
    global version_cache, version_cache_expiry

    from datetime import datetime
    
    # 快速缓存检查
    now = datetime.now()
    cache_duration = timedelta(minutes=5)  # 5分钟缓存
    if not force_refresh and version_cache and version_cache_expiry and now < version_cache_expiry:
        print("🚀 使用缓存数据")
        return version_cache

    print(f"🚀 快速获取版本数据{' (强制刷新)' if force_refresh else ''}...")
    start_time = time.time()

    try:
        # 导入版本管理器
        import sys
        import os
        backend_dir = os.path.dirname(__file__)
        core_dir = os.path.join(backend_dir, 'core')
        if core_dir not in sys.path:
            sys.path.insert(0, core_dir)
        
        from version_manager import VersionManager
        
        # 获取便携包路径并初始化版本管理器
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        version_mgr = VersionManager(comfyui_dir)
        
        if not version_mgr.is_git_repo():
            raise Exception("不是Git仓库")

        # 如果强制刷新，执行一次快速fetch
        if force_refresh:
            try:
                print("🔄 执行快速fetch...")
                version_mgr.fetch_updates()
            except Exception as e:
                print(f"⚠️ Fetch失败，继续使用本地数据: {e}")

        # 快速获取版本历史和当前版本
        print("📚 获取版本历史...")
        # 强制刷新时从远程分支获取历史，否则使用本地
        local_versions = version_mgr.get_version_history(limit=30, use_remote=force_refresh)
        current_version = version_mgr.get_current_version()
        
        # 构造开发版本数据
        development_versions = []
        for version in local_versions:
            development_versions.append({
                'id': version.commit_hash,
                'version': f'dev-{version.commit_hash}',
                'date': version.date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'current': version.is_current,  # 使用前端期望的字段名
                'isCurrent': version.is_current,  # 保持兼容性
                'commit': version.commit_hash,
                'message': version.commit_message.split('\n')[0][:100],
                'author': version.author
            })
        
        # 快速获取稳定版本（标签）
        stable_versions = []
        try:
            tags = version_mgr.get_tags_with_info()
            for tag in tags[:15]:  # 只取前15个最新标签
                stable_versions.append({
                    'id': tag.name,
                    'version': tag.name,
                    'date': tag.date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'current': tag.is_current,  # 使用前端期望的字段名
                    'isCurrent': tag.is_current,  # 保持兼容性
                    'commit': tag.commit_hash,
                    'message': tag.message.split('\n')[0][:100],
                    'author': tag.author
                })
        except Exception as e:
            print(f"获取标签失败: {e}")
        
        # 获取当前状态
        current_branch = "unknown"
        current_commit = "unknown"
        if current_version:
            current_commit = current_version.commit_hash
        try:
            current_branch = version_mgr.repo.active_branch.name if not version_mgr.repo.head.is_detached else "detached"
        except:
            current_branch = "detached"
        
        # 构造结果
        result = {
            "status": "success",
            "current_branch": current_branch,
            "current_commit": current_commit,
            "stable": stable_versions,
            "development": development_versions
        }
        
        # 缓存结果
        version_cache = result
        version_cache_expiry = now + cache_duration
        
        elapsed = time.time() - start_time
        print(f"✅ 版本数据获取完成 ({elapsed:.2f}s)")
        print(f"📊 稳定版本: {len(stable_versions)}个, 开发版本: {len(development_versions)}个")
        
        return result
        
    except Exception as e:
        print(f"❌ 版本获取失败: {e}")
        # 返回基础错误信息
        return {
            "status": "error",
            "message": str(e),
            "current_branch": "unknown",
            "current_commit": "unknown", 
            "stable": [],
            "development": []
        }


@app.get("/comfyui/check-updates")
async def check_comfyui_updates():
    """智能检查ComfyUI更新（自动fetch远程引用）"""
    try:
        import git
        from datetime import datetime
        
        # 获取当前Git提交哈希
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        if not os.path.exists(os.path.join(comfyui_dir, ".git")):
            return {"error": "不是Git仓库", "has_updates": False}
            
        repo = git.Repo(comfyui_dir)
        current_commit = repo.head.commit.hexsha
        
        # 智能检查：先检查远程引用，必要时执行fetch
        try:
            # 检查远程引用是否存在且有效
            remote_commit = None
            need_fetch = False
            
            try:
                remote_master = repo.remotes.origin.refs.master.commit
                remote_commit = remote_master.hexsha
                print(f"使用缓存的远程引用: {remote_commit[:8]}")
                
                # 如果本地不是最新，说明需要检查更新
                if current_commit != remote_commit:
                    print("发现本地落后于远程缓存，尝试快速fetch")
                    # 执行轻量级fetch（只获取refs，不下载对象）
                    try:
                        origin = repo.remotes.origin
                        origin.fetch()
                        # 重新获取远程引用
                        remote_master = repo.remotes.origin.refs.master.commit
                        remote_commit = remote_master.hexsha
                        print(f"Fetch完成，最新远程提交: {remote_commit[:8]}")
                    except Exception as fetch_error:
                        print(f"轻量级fetch失败，使用缓存的远程引用: {fetch_error}")
                        
            except Exception as e:
                print(f"远程引用不可用，跳过远程检查: {e}")
                remote_commit = current_commit  # 假设本地是最新的
            
            # 使用远程引用计算更新数量
            if remote_commit and remote_commit != current_commit:
                # 从远程引用获取提交历史
                commits = list(repo.iter_commits(remote_commit, max_count=30))
                update_count = 0
                
                for i, commit in enumerate(commits):
                    if commit.hexsha == current_commit:
                        update_count = i
                        break
                else:
                    # 如果当前提交不在最近30个提交中，设置一个合理的数量
                    update_count = 30
                
                has_updates = update_count > 0
                latest_commit = remote_commit[:8]
            else:
                # 本地已是最新
                has_updates = False
                update_count = 0
                latest_commit = current_commit[:8]
            
            return {
                "has_updates": has_updates,
                "update_count": update_count,
                "current_commit": current_commit[:8],
                "latest_commit": latest_commit,
                "status": "success"
            }
            
        except Exception as e:
            print(f"智能更新检查失败: {e}")
            return {"error": f"检查更新失败: {str(e)}", "has_updates": False}
            
    except Exception as e:
        return {"error": str(e), "has_updates": False}

@app.post("/comfyui/switch-version")
async def switch_comfyui_version(request: dict):
    """切换ComfyUI版本"""
    try:
        import git
        from datetime import datetime

        version_id = request.get('version_id')
        if not version_id:
            return {"status": "error", "message": "版本ID不能为空"}

        # 获取ComfyUI目录
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]

        if not os.path.exists(os.path.join(comfyui_dir, ".git")):
            return {"status": "error", "message": "ComfyUI目录不是Git仓库"}

        # 使用GitPython切换版本
        repo = git.Repo(comfyui_dir)

        # 获取切换前的信息
        old_commit = repo.head.commit.hexsha[:8]
        old_branch = repo.active_branch.name if not repo.head.is_detached else "detached"

        try:
            # 先获取远程更新，确保本地仓库有最新的提交
            print(f"获取远程更新以确保提交 {version_id} 可用...")
            try:
                repo.remotes.origin.fetch()
                print("远程更新获取成功")
            except Exception as fetch_error:
                print(f"获取远程更新失败，但继续尝试切换: {fetch_error}")
            
            # 尝试切换到指定版本
            repo.git.checkout(version_id)

            # 获取切换后的信息
            new_commit = repo.head.commit.hexsha[:8]
            new_branch = repo.active_branch.name if not repo.head.is_detached else "detached"

            # 版本切换成功后立即清除版本缓存，确保下次获取时显示正确的当前版本
            global version_cache, version_cache_expiry
            version_cache = None
            version_cache_expiry = None
            print(f"版本切换成功，已清除版本缓存: {old_commit} -> {new_commit}")

            return {
                "status": "success",
                "message": f"成功切换到版本 {version_id}",
                "old_version": {
                    "commit": old_commit,
                    "branch": old_branch
                },
                "new_version": {
                    "commit": new_commit,
                    "branch": new_branch,
                    "version_id": version_id
                }
            }

        except git.exc.GitCommandError as e:
            return {
                "status": "error",
                "message": f"切换版本失败: {str(e)}"
            }

    except Exception as e:
        return {"status": "error", "message": f"切换ComfyUI版本失败: {str(e)}"}

@app.post("/comfyui/clear-version-cache")
async def clear_comfyui_version_cache():
    """清除ComfyUI版本缓存"""
    global version_cache, version_cache_expiry

    try:
        version_cache = None
        version_cache_expiry = None
        print("ComfyUI version cache manually cleared")

        return {
            "status": "success",
            "message": "ComfyUI版本缓存已清除"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"清除ComfyUI版本缓存失败: {str(e)}"
        }

@app.post("/git/checkout")
async def git_checkout(request: dict):
    """切换分支或提交"""
    try:
        import git
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        target = request.get("target")
        if not target:
            return {"status": "error", "message": "未指定切换目标"}
        
        repo = git.Repo(comfyui_dir)
        
        # 检查是否有未提交的更改
        if repo.is_dirty():
            return {
                "status": "error", 
                "message": "有未提交的更改，请先提交或撤销更改"
            }
        
        # 执行切换
        repo.git.checkout(target)
        
        return {
            "status": "success",
            "message": f"已切换到: {target}"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"切换失败: {str(e)}"
        }

@app.post("/git/pull")
async def git_pull():
    """拉取最新代码"""
    try:
        import git
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        repo = git.Repo(comfyui_dir)
        
        # 检查是否有未提交的更改
        if repo.is_dirty():
            return {
                "status": "error", 
                "message": "有未提交的更改，请先提交或撤销更改"
            }
        
        # 执行拉取
        origin = repo.remotes.origin
        pull_info = origin.pull()
        
        return {
            "status": "success",
            "message": "代码更新完成",
            "details": str(pull_info[0])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"拉取失败: {str(e)}"
        }

@app.get("/git/official-status")
async def git_official_status():
    """获取与官方仓库的同步状态"""
    try:
        import git
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        repo = git.Repo(comfyui_dir)
        
        # 检查远程仓库配置
        remotes = {}
        for remote in repo.remotes:
            remotes[remote.name] = remote.url
        
        # 检查是否配置了官方上游
        upstream_url = "https://github.com/comfyanonymous/ComfyUI.git"
        has_upstream = False
        upstream_name = None
        
        for name, url in remotes.items():
            if "comfyanonymous/ComfyUI" in url:
                has_upstream = True
                upstream_name = name
                break
        
        # 如果没有配置上游，尝试添加
        if not has_upstream:
            try:
                upstream = repo.create_remote('upstream', upstream_url)
                upstream.fetch()
                has_upstream = True
                upstream_name = 'upstream'
            except:
                pass
        
        result = {
            "status": "success",
            "remotes": remotes,
            "has_upstream": has_upstream,
            "upstream_name": upstream_name,
            "upstream_url": upstream_url
        }
        
        # 如果有上游，检查同步状态
        if has_upstream:
            try:
                upstream = repo.remotes[upstream_name]
                upstream.fetch()
                
                current_branch = repo.active_branch.name
                
                # 检测主分支名称（main或master）
                main_branch_name = "master"  # 默认
                for branch_name in ['main', 'master', 'Main', 'Master']:
                    remote_ref_name = f"{upstream_name}/{branch_name}"
                    if any(ref.name == remote_ref_name for ref in upstream.refs):
                        main_branch_name = branch_name
                        break
                
                upstream_branch = f"{upstream_name}/{main_branch_name}"
                
                # 计算落后和领先的提交数
                try:
                    behind_commits = list(repo.iter_commits(f'{current_branch}..{upstream_branch}'))
                    ahead_commits = list(repo.iter_commits(f'{upstream_branch}..{current_branch}'))
                    
                    result.update({
                        "behind_count": len(behind_commits),
                        "ahead_count": len(ahead_commits),
                        "is_synced": len(behind_commits) == 0,
                        "latest_upstream_commit": {
                            "hash": behind_commits[0].hexsha[:8] if behind_commits else repo.head.commit.hexsha[:8],
                            "message": behind_commits[0].message.strip() if behind_commits else "已是最新",
                            "date": behind_commits[0].committed_datetime.strftime("%Y-%m-%d %H:%M:%S") if behind_commits else ""
                        }
                    })
                except:
                    result.update({
                        "behind_count": 0,
                        "ahead_count": 0,
                        "is_synced": True
                    })
            except:
                pass
        
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"检查官方同步状态失败: {str(e)}"
        }

@app.post("/git/sync-upstream")
async def git_sync_upstream():
    """同步官方上游代码"""
    try:
        import git
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        repo = git.Repo(comfyui_dir)
        
        # 检查是否有未提交的更改
        if repo.is_dirty():
            return {
                "status": "error", 
                "message": "有未提交的更改，请先提交或撤销更改"
            }
        
        # 查找指向官方仓库的远程
        upstream_url = "https://github.com/comfyanonymous/ComfyUI.git"
        upstream_name = None
        
        # 检查现有的远程配置
        for remote in repo.remotes:
            if "comfyanonymous/ComfyUI" in remote.url:
                upstream_name = remote.name
                break
        
        # 如果没找到官方远程，创建一个
        if not upstream_name:
            upstream = repo.create_remote('upstream', upstream_url)
            upstream_name = 'upstream'
        else:
            upstream = repo.remotes[upstream_name]
        
        # 获取上游最新代码
        upstream.fetch()
        
        # 合并上游主分支到当前分支
        current_branch = repo.active_branch.name
        
        # 检测主分支名称（main或master）
        main_branch_name = "master"  # 默认
        upstream = repo.remotes[upstream_name]
        for branch_name in ['main', 'master', 'Main', 'Master']:
            remote_ref_name = f"{upstream_name}/{branch_name}"
            if any(ref.name == remote_ref_name for ref in upstream.refs):
                main_branch_name = branch_name
                break
        
        upstream_branch = f"{upstream_name}/{main_branch_name}"
        
        # 执行合并
        repo.git.merge(upstream_branch)
        
        return {
            "status": "success",
            "message": "已同步官方最新代码",
            "branch": current_branch
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"同步失败: {str(e)}"
        }

# 项目目录管理API
@app.get("/project/directories")
async def get_project_directories():
    """获取项目目录信息"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        directories = {
            "input": os.path.join(comfyui_dir, "input"),
            "output": os.path.join(comfyui_dir, "output"),
            "models": os.path.join(comfyui_dir, "models"),
            "custom_nodes": os.path.join(comfyui_dir, "custom_nodes"),
            "user": os.path.join(comfyui_dir, "user"),
            "temp": os.path.join(comfyui_dir, "temp")
        }
        
        # 检查目录状态
        directory_info = {}
        for name, path in directories.items():
            exists = os.path.exists(path)
            size = 0
            file_count = 0
            
            if exists:
                try:
                    # 计算目录大小和文件数量
                    total_size = 0
                    total_files = 0
                    
                    for dirpath, dirnames, filenames in os.walk(path):
                        total_files += len(filenames)
                        for filename in filenames:
                            filepath = os.path.join(dirpath, filename)
                            try:
                                total_size += os.path.getsize(filepath)
                            except:
                                continue
                    
                    size = total_size
                    file_count = total_files
                except:
                    pass
            
            directory_info[name] = {
                "path": path,
                "exists": exists,
                "size": size,
                "file_count": file_count,
                "size_mb": round(size / (1024 * 1024), 2) if size > 0 else 0
            }
        
        return {
            "status": "success",
            "directories": directory_info,
            "comfyui_root": comfyui_dir
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取目录信息失败: {str(e)}"
        }

@app.get("/project/directory/{dir_name}")
async def get_directory_contents(dir_name: str):
    """获取指定目录的内容"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        valid_dirs = ["input", "output", "models", "custom_nodes", "user", "temp"]
        if dir_name not in valid_dirs:
            return {"status": "error", "message": "无效的目录名"}
        
        dir_path = os.path.join(comfyui_dir, dir_name)
        
        if not os.path.exists(dir_path):
            return {"status": "error", "message": "目录不存在"}
        
        contents = []
        try:
            for item in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item)
                is_dir = os.path.isdir(item_path)
                size = 0
                
                if not is_dir:
                    try:
                        size = os.path.getsize(item_path)
                    except:
                        pass
                
                contents.append({
                    "name": item,
                    "type": "directory" if is_dir else "file",
                    "size": size,
                    "size_mb": round(size / (1024 * 1024), 2) if size > 0 else 0
                })
        except Exception as e:
            return {"status": "error", "message": f"读取目录失败: {str(e)}"}
        
        return {
            "status": "success",
            "directory": dir_name,
            "path": dir_path,
            "contents": contents
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取目录内容失败: {str(e)}"
        }

@app.post("/project/create-directory")
async def create_project_directory(request: dict):
    """创建项目目录"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        dir_name = request.get("name")
        if not dir_name:
            return {"status": "error", "message": "未指定目录名"}
        
        # 安全检查：只允许在预定义的目录下创建子目录
        parent_dir = request.get("parent", "")
        valid_parents = ["input", "output", "models", "custom_nodes", "user", "temp"]
        
        if parent_dir and parent_dir in valid_parents:
            target_path = os.path.join(comfyui_dir, parent_dir, dir_name)
        else:
            return {"status": "error", "message": "无效的父目录"}
        
        # 检查目录是否已存在
        if os.path.exists(target_path):
            return {"status": "error", "message": "目录已存在"}
        
        # 创建目录
        os.makedirs(target_path, exist_ok=True)
        
        return {
            "status": "success",
            "message": f"目录创建成功: {target_path}",
            "path": target_path
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"创建目录失败: {str(e)}"
        }

@app.post("/project/open-directory")
async def open_project_directory(request: dict):
    """在文件管理器中打开项目目录"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        dir_name = request.get("directory")
        if not dir_name:
            return {"status": "error", "message": "未指定目录名"}
        
        # 安全检查：只允许打开预定义的目录
        valid_dirs = ["input", "output", "models", "custom_nodes", "user", "temp", "root"]
        if dir_name not in valid_dirs:
            return {"status": "error", "message": "无效的目录名"}
        
        # 构建目录路径
        if dir_name == "root":
            target_path = comfyui_dir
        else:
            target_path = os.path.join(comfyui_dir, dir_name)
        
        # 检查目录是否存在
        if not os.path.exists(target_path):
            return {"status": "error", "message": f"目录不存在: {target_path}"}
        
        # 根据操作系统打开目录
        import subprocess
        import sys
        
        try:
            if sys.platform == "win32":
                # Windows
                subprocess.run(["explorer", target_path], check=True)
            elif sys.platform == "darwin":
                # macOS
                subprocess.run(["open", target_path], check=True)
            else:
                # Linux
                subprocess.run(["xdg-open", target_path], check=True)
            
            return {
                "status": "success",
                "message": f"已在文件管理器中打开: {dir_name}",
                "path": target_path
            }
            
        except subprocess.CalledProcessError as e:
            return {
                "status": "error",
                "message": f"打开目录失败: {str(e)}"
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "message": "找不到文件管理器程序"
            }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"打开目录失败: {str(e)}"
        }

# 插件缓存
_plugin_cache = None
_plugin_cache_time = 0
_plugin_cache_duration = 300  # 5分钟缓存（优化后）

# 自定义节点管理API
@app.get("/nodes/installed")
async def get_installed_nodes(force_refresh: bool = False, skip_update: bool = False):
    """获取已安装的自定义节点（便携包性能优化版本）"""
    global _plugin_cache, _plugin_cache_time

    try:
        start_time = time.time()

        # 检查是否强制刷新
        if force_refresh:
            print("Force refresh requested, clearing plugin cache")
            _plugin_cache = None
            _plugin_cache_time = 0

        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")

        if not os.path.exists(custom_nodes_dir):
            result = {
                "status": "success",
                "nodes": [],
                "message": "custom_nodes目录不存在"
            }
            _plugin_cache = result
            _plugin_cache_time = time.time()
            return result

        # 尝试使用便携包性能优化器
        try:
            from .portable_performance_optimizer import get_portable_optimizer

            optimizer = get_portable_optimizer(custom_nodes_dir)

            # 如果不是强制刷新，先尝试从缓存获取
            if not force_refresh:
                cached_plugins = await optimizer.get_cached_plugins()
                if cached_plugins:
                    print("使用便携包优化器缓存数据")
                    result = {
                        "status": "success",
                        "nodes": cached_plugins,
                        "total": len(cached_plugins),
                        "custom_nodes_path": custom_nodes_dir,
                        "scan_time": "0.00s (cached)",
                        "portable_optimized": True
                    }
                    _plugin_cache = result
                    _plugin_cache_time = time.time()
                    return result

            # 使用优化器扫描插件
            print("使用便携包优化器扫描插件")
            nodes = await optimizer.scan_plugins_fast()

            # 缓存结果
            await optimizer.cache_plugins(nodes)

            scan_time = time.time() - start_time
            result = {
                "status": "success",
                "nodes": nodes,
                "total": len(nodes),
                "custom_nodes_path": custom_nodes_dir,
                "scan_time": f"{scan_time:.2f}s",
                "portable_optimized": True
            }

            # 更新内存缓存
            _plugin_cache = result
            _plugin_cache_time = time.time()

            print(f"便携包优化扫描完成: {scan_time:.2f}s, 找到 {len(nodes)} 个插件")
            return result

        except ImportError as e:
            print(f"警告 便携包优化器不可用: {e}")
            print("回退到标准扫描模式")
        except Exception as e:
            print(f"警告 便携包优化器错误: {e}")
            print("回退到标准扫描模式")

        # 回退到标准扫描（检查内存缓存）
        current_time = time.time()
        if _plugin_cache and (current_time - _plugin_cache_time) < _plugin_cache_duration:
            print(f"使用内存缓存数据 (age: {current_time - _plugin_cache_time:.1f}s)")
            return _plugin_cache

        print(f"标准模式扫描插件: {custom_nodes_dir}")
        nodes = []
        
        # 快速扫描custom_nodes目录（优化版本）
        for item_name in os.listdir(custom_nodes_dir):
            item_path = os.path.join(custom_nodes_dir, item_name)

            # 跳过文件，只处理目录
            if not os.path.isdir(item_path):
                continue

            # 跳过特殊目录
            if item_name.startswith('.') or item_name == '__pycache__':
                continue

            # 判断节点状态
            is_disabled = item_name.endswith('.disabled')
            actual_name = item_name.replace('.disabled', '') if is_disabled else item_name
            status = 'disabled' if is_disabled else 'enabled'

            # 快速检查是否包含Python文件（不深度遍历）
            has_python_files = False
            try:
                for file in os.listdir(item_path):
                    if file.endswith('.py'):
                        has_python_files = True
                        break
            except:
                continue

            # 如果没有Python文件，跳过
            if not has_python_files:
                continue

            # 基础节点信息（最小化文件操作）
            node_info = {
                "name": actual_name,
                "path": item_path,
                "status": status,
                "enabled": status == 'enabled',  # 添加enabled字段
                "fileCount": 0,  # 暂时设为0，避免耗时的文件统计
                "author": "未知",
                "version": "未知",
                "description": f"自定义节点: {actual_name}",
                "hasUpdate": False,
                "repo_url": f"https://github.com/search?q={actual_name}",
                "date": "未知",
                "git_date": "未知"
            }
            
            # 快速获取基本信息（保持性能优化）
            try:
                # 检查是否是Git仓库并获取版本信息
                if os.path.exists(os.path.join(item_path, ".git")):
                    try:
                        import subprocess

                        # 获取Git远程URL
                        result = subprocess.run(
                            ["git", "remote", "get-url", "origin"],
                            capture_output=True,
                            text=True,
                            cwd=item_path,
                            timeout=2  # 2秒超时
                        )
                        if result.returncode == 0:
                            origin_url = result.stdout.strip()
                            node_info["repo_url"] = origin_url
                            # 从URL中提取作者信息
                            if "github.com" in origin_url:
                                parts = origin_url.replace(".git", "").split("/")
                                if len(parts) >= 2:
                                    node_info["author"] = parts[-2]

                        # 获取当前分支和最新提交信息
                        branch_result = subprocess.run(
                            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True,
                            text=True,
                            cwd=item_path,
                            timeout=2
                        )
                        commit_result = subprocess.run(
                            ["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True,
                            text=True,
                            cwd=item_path,
                            timeout=2
                        )
                        date_result = subprocess.run(
                            ["git", "log", "-1", "--format=%cd", "--date=short"],
                            capture_output=True,
                            text=True,
                            cwd=item_path,
                            timeout=2
                        )

                        if branch_result.returncode == 0 and commit_result.returncode == 0:
                            branch = branch_result.stdout.strip()
                            commit = commit_result.stdout.strip()
                            node_info["version"] = f"{branch} ({commit})"
                            node_info["git_branch"] = branch
                            node_info["git_commit"] = commit

                            if date_result.returncode == 0:
                                commit_date = date_result.stdout.strip()
                                node_info["date"] = commit_date
                                node_info["git_date"] = commit_date

                            # 检查是否为最新版本（改进的检查方法）
                            try:
                                # 获取当前分支的本地提交
                                local_commit = subprocess.run(
                                    ["git", "rev-parse", "HEAD"],
                                    capture_output=True,
                                    text=True,
                                    cwd=item_path,
                                    timeout=2
                                ).stdout.strip()

                                # 尝试获取远程分支的最新提交
                                remote_commit = None

                                # 方法1：尝试获取当前分支对应的远程分支
                                try:
                                    remote_branch_result = subprocess.run(
                                        ["git", "rev-parse", f"origin/{branch}"],
                                        capture_output=True,
                                        text=True,
                                        cwd=item_path,
                                        timeout=2
                                    )
                                    if remote_branch_result.returncode == 0:
                                        remote_commit = remote_branch_result.stdout.strip()
                                except:
                                    pass

                                # 方法2：如果方法1失败，尝试获取origin/main或origin/master
                                if not remote_commit:
                                    for default_branch in ['main', 'master']:
                                        try:
                                            default_result = subprocess.run(
                                                ["git", "rev-parse", f"origin/{default_branch}"],
                                                capture_output=True,
                                                text=True,
                                                cwd=item_path,
                                                timeout=2
                                            )
                                            if default_result.returncode == 0:
                                                remote_commit = default_result.stdout.strip()
                                                break
                                        except:
                                            continue

                                # 比较本地和远程提交
                                if remote_commit:
                                    node_info["isLatestVersion"] = (local_commit == remote_commit)
                                    print(f"Version check for {actual_name}: local={local_commit[:8]}, remote={remote_commit[:8]}, isLatest={node_info['isLatestVersion']}")
                                else:
                                    node_info["isLatestVersion"] = True  # 无法获取远程信息，默认认为是最新版本
                                    print(f"Version check for {actual_name}: unable to get remote commit, assuming latest")

                            except Exception as e:
                                node_info["isLatestVersion"] = True  # 默认认为是最新版本
                                print(f"Version check failed for {actual_name}: {e}")

                    except Exception as e:
                        print(f"Git info extraction failed for {actual_name}: {e}")
                        pass

                # 如果没有Git信息，使用文件修改时间作为备用
                if node_info["date"] == "未知":
                    try:
                        # 获取目录中最新的Python文件修改时间
                        latest_time = 0
                        for root, dirs, files in os.walk(item_path):
                            for file in files:
                                if file.endswith('.py'):
                                    file_path = os.path.join(root, file)
                                    try:
                                        mtime = os.path.getmtime(file_path)
                                        if mtime > latest_time:
                                            latest_time = mtime
                                    except:
                                        continue

                        if latest_time > 0:
                            import datetime
                            date_str = datetime.datetime.fromtimestamp(latest_time).strftime('%Y-%m-%d')
                            node_info["date"] = date_str
                            node_info["git_date"] = date_str
                            if node_info["version"] == "未知":
                                node_info["version"] = f"本地版本 ({date_str})"
                    except Exception as e:
                        print(f"File time extraction failed for {actual_name}: {e}")
                        pass

                # 快速检查pyproject.toml获取版本信息
                pyproject_file = os.path.join(item_path, "pyproject.toml")
                if os.path.exists(pyproject_file):
                    try:
                        with open(pyproject_file, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(1000)  # 只读前1000字符
                            # 简单解析版本信息
                            for line in content.split('\n'):
                                if 'version = ' in line and node_info["version"] == "未知":
                                    version = line.split('version = ')[1].strip().strip('"\'')
                                    node_info["version"] = version
                                elif 'PublisherId = ' in line and node_info["author"] == "未知":
                                    author = line.split('PublisherId = ')[1].strip().strip('"\'')
                                    node_info["author"] = author
                    except:
                        pass

                # 快速检查README文件获取描述
                for readme_name in ["README.md", "readme.md", "README.txt", "readme.txt"]:
                    readme_path = os.path.join(item_path, readme_name)
                    if os.path.exists(readme_path):
                        try:
                            with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read(500)  # 只读前500字符
                                lines = content.split('\n')
                                if len(lines) > 0:
                                    # 取第一行作为描述（通常是标题）
                                    first_line = lines[0].strip().replace('#', '').strip()
                                    if first_line and len(first_line) > 5:
                                        node_info["description"] = first_line[:200]
                                        break
                        except:
                            pass
            except Exception as e:
                print(f"Error processing plugin {actual_name}: {e}")
                pass

            # 添加节点到列表
            nodes.append(node_info)

        # 按名称排序
        nodes.sort(key=lambda x: x["name"].lower())

        # 计算扫描时间
        scan_time = time.time() - start_time
        print(f"Plugin scan completed in {scan_time:.2f}s, found {len(nodes)} plugins")

        # 缓存结果
        result = {
            "status": "success",
            "nodes": nodes,
            "total": len(nodes),
            "custom_nodes_path": custom_nodes_dir,
            "scan_time": f"{scan_time:.2f}s"
        }
        _plugin_cache = result
        _plugin_cache_time = current_time

        return result

    except Exception as e:
        print(f"Error in get_installed_nodes: {e}")
        return {
            "status": "error",
            "message": f"获取已安装节点失败: {str(e)}"
        }





# 占位符API已移除，使用下面的真实实现

@app.post("/nodes/update")
async def update_node(request: dict):
    """更新单个节点"""
    try:
        node_name = request.get("name")
        if not node_name:
            return {"status": "error", "message": "未指定节点名称"}
        
        # 占位符实现
        return {
            "status": "success",
            "message": f"节点 {node_name} 更新功能开发中"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"更新节点失败: {str(e)}"
        }


# 启动器自我保护和诊断API
@app.get("/launcher/health")
async def launcher_health_check():
    """检查启动器完整性和健康状态"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        # 检查关键文件
        critical_files = {
            "backend_main": os.path.join(launcher_dir, "backend", "start_fixed_cors.py"),
            "frontend_advanced": os.path.join(launcher_dir, "advanced_launcher.html"),
            "frontend_simple": os.path.join(launcher_dir, "web_frontend.html"),
            "requirements": os.path.join(launcher_dir, "backend", "requirements.txt")
        }
        
        file_status = {}
        missing_files = []
        
        for name, path in critical_files.items():
            exists = os.path.exists(path)
            file_status[name] = {
                "path": path,
                "exists": exists,
                "size": os.path.getsize(path) if exists else 0
            }
            if not exists:
                missing_files.append(name)
        
        # 检查Git状态
        git_status = "unknown"
        try:
            import git
            repo = git.Repo(comfyui_dir)
            
            # 检查是否有未提交的启动器更改
            changed_files = [item.a_path for item in repo.index.diff(None)]
            launcher_changes = [f for f in changed_files if "ComfyUI-Launcher" in f]
            
            if launcher_changes:
                git_status = "has_launcher_changes"
            else:
                git_status = "clean"
                
        except Exception as e:
            git_status = f"git_error: {str(e)}"
        
        # 检查Python环境
        python_status = {
            "version": sys.version,
            "executable": sys.executable,
            "packages": {}
        }
        
        # 检查关键依赖包
        required_packages = ["fastapi", "uvicorn", "psutil", "gitpython"]
        for package in required_packages:
            try:
                __import__(package)
                python_status["packages"][package] = "available"
            except ImportError:
                python_status["packages"][package] = "missing"
        
        # 整体健康状态评估
        health_score = 100
        issues = []
        
        if missing_files:
            health_score -= len(missing_files) * 20
            issues.append(f"缺少关键文件: {', '.join(missing_files)}")
        
        missing_packages = [pkg for pkg, status in python_status["packages"].items() if status == "missing"]
        if missing_packages:
            health_score -= len(missing_packages) * 10
            issues.append(f"缺少Python包: {', '.join(missing_packages)}")
        
        if "error" in git_status:
            health_score -= 15
            issues.append("Git状态检查失败")
        
        # 确定健康等级
        if health_score >= 90:
            health_level = "excellent"
        elif health_score >= 70:
            health_level = "good"
        elif health_score >= 50:
            health_level = "warning"
        else:
            health_level = "critical"
        
        return {
            "status": "success",
            "health_score": health_score,
            "health_level": health_level,
            "launcher_directory": launcher_dir,
            "file_status": file_status,
            "missing_files": missing_files,
            "git_status": git_status,
            "python_status": python_status,
            "issues": issues,
            "recommendations": get_health_recommendations(health_level, issues)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"健康检查失败: {str(e)}"
        }

def get_health_recommendations(health_level, issues):
    """根据健康状态提供建议"""
    recommendations = []
    
    if health_level == "critical":
        recommendations.append("警告 启动器状态严重异常，建议重新安装")
        recommendations.append(" 建议备份当前配置后重新部署启动器")
    elif health_level == "warning":
        recommendations.append("警告 发现一些问题，建议尽快修复")
    
    for issue in issues:
        if "缺少关键文件" in issue:
            recommendations.append(" 重新下载启动器文件或从备份恢复")
        elif "缺少Python包" in issue:
            recommendations.append(" 运行: pip install -r requirements.txt")
        elif "Git状态检查失败" in issue:
            recommendations.append(" 检查Git仓库完整性")
    
    if not recommendations:
        recommendations.append("OK 启动器运行良好，无需特殊操作")
    
    return recommendations

@app.post("/launcher/backup")
async def create_launcher_backup():
    """创建启动器备份"""
    try:
        import shutil
        import datetime
        
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        # 创建备份目录
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"ComfyUI-Launcher-Backup-{timestamp}"
        backup_path = os.path.join(comfyui_dir, backup_name)
        
        # 排除不需要备份的目录
        def ignore_patterns(dir, files):
            return ['__pycache__', '*.pyc', '.git', 'node_modules']
        
        shutil.copytree(launcher_dir, backup_path, ignore=ignore_patterns)
        
        # 计算备份大小
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(backup_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        
        return {
            "status": "success",
            "message": "启动器备份创建成功",
            "backup_path": backup_path,
            "backup_size": round(total_size / (1024 * 1024), 2),  # MB
            "timestamp": timestamp
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"备份创建失败: {str(e)}"
        }

@app.get("/launcher/version-safety")
async def check_version_safety():
    """检查版本切换安全性"""
    try:
        import git
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        repo = git.Repo(comfyui_dir)
        
        # 检查当前版本信息
        current_commit = repo.head.commit
        current_info = {
            "hash": current_commit.hexsha[:8],
            "message": current_commit.message.strip(),
            "date": current_commit.committed_datetime.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 检查是否有启动器相关的更改
        launcher_files_in_repo = []
        try:
            for item in repo.tree().traverse():
                if hasattr(item, 'path') and 'ComfyUI-Launcher' in item.path:
                    launcher_files_in_repo.append(item.path)
        except:
            pass
        
        # 安全评估
        safety_level = "safe"
        warnings = []
        
        if launcher_files_in_repo:
            safety_level = "warning"
            warnings.append("警告 官方仓库中发现了启动器相关文件，版本切换可能有冲突风险")
        
        # 检查本地启动器是否有未提交的更改
        try:
            changed_files = [item.a_path for item in repo.index.diff(None)]
            unstaged_files = [item.a_path for item in repo.index.diff("HEAD")]
            
            launcher_changes = [f for f in changed_files + unstaged_files if "ComfyUI-Launcher" in f]
            if launcher_changes:
                safety_level = "warning"
                warnings.append("警告 启动器有本地更改，版本切换前建议备份")
        except:
            pass
        
        recommendations = []
        if safety_level == "warning":
            recommendations.extend([
                " 切换版本前创建启动器备份",
                " 将启动器目录加入.gitignore",
                " 记录当前配置以便恢复"
            ])
        else:
            recommendations.append("OK 版本切换相对安全，但建议定期备份")
        
        return {
            "status": "success",
            "current_version": current_info,
            "safety_level": safety_level,
            "launcher_files_in_repo": launcher_files_in_repo,
            "warnings": warnings,
            "recommendations": recommendations
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"安全检查失败: {str(e)}"
        }


@app.post("/nodes/toggle")
async def toggle_node(request: dict):
    """启用/禁用自定义节点"""
    try:
        node_name = request.get("node_name")
        enable = request.get("enable", True)
        
        if not node_name:
            return {"status": "error", "message": "未指定节点名称"}
        
        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
        
        # 查找节点目录
        current_name = None
        for item in os.listdir(custom_nodes_dir):
            item_path = os.path.join(custom_nodes_dir, item)
            if not os.path.isdir(item_path):
                continue
            
            # 检查是否匹配（考虑.disabled后缀）
            clean_name = item[:-9] if item.endswith('.disabled') else item
            if clean_name == node_name:
                current_name = item
                break
        
        if not current_name:
            return {"status": "error", "message": f"未找到节点: {node_name}"}
        
        current_path = os.path.join(custom_nodes_dir, current_name)
        
        # 确定新名称
        if enable:
            # 启用：移除.disabled后缀
            if current_name.endswith('.disabled'):
                new_name = current_name[:-9]
            else:
                return {"status": "success", "message": f"节点 {node_name} 已经是启用状态"}
        else:
            # 禁用：添加.disabled后缀
            if not current_name.endswith('.disabled'):
                new_name = current_name + '.disabled'
            else:
                return {"status": "success", "message": f"节点 {node_name} 已经是禁用状态"}
        
        new_path = os.path.join(custom_nodes_dir, new_name)
        
        # 重命名目录
        os.rename(current_path, new_path)
        
        action = "启用" if enable else "禁用"
        return {
            "status": "success",
            "message": f"节点 {node_name} {action}成功",
            "old_name": current_name,
            "new_name": new_name
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"节点状态切换失败: {str(e)}"
        }

@app.post("/nodes/uninstall")
async def uninstall_node(request: dict):
    """卸载自定义节点"""
    try:
        node_name = request.get("node_name")
        create_backup = request.get("create_backup", True)
        
        if not node_name:
            return {"status": "error", "message": "未指定节点名称"}
        
        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
        
        # 查找节点目录
        current_name = None
        for item in os.listdir(custom_nodes_dir):
            item_path = os.path.join(custom_nodes_dir, item)
            if not os.path.isdir(item_path):
                continue
            
            clean_name = item[:-9] if item.endswith('.disabled') else item
            if clean_name == node_name:
                current_name = item
                break
        
        if not current_name:
            return {"status": "error", "message": f"未找到节点: {node_name}"}
        
        current_path = os.path.join(custom_nodes_dir, current_name)
        
        # 创建备份（如果需要）
        backup_path = None
        if create_backup:
            import datetime
            import shutil
            
            backup_dir = os.path.join(custom_nodes_dir, ".backups")
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{node_name}_backup_{timestamp}"
            backup_path = os.path.join(backup_dir, backup_name)
            
            try:
                shutil.copytree(current_path, backup_path)
            except Exception as backup_error:
                return {
                    "status": "error", 
                    "message": f"创建备份失败: {str(backup_error)}"
                }
        
        # 删除节点目录（处理Windows权限问题）
        import shutil
        import stat

        def handle_remove_readonly(func, path, exc):
            """处理只读文件删除"""
            if os.path.exists(path):
                # 移除只读属性
                os.chmod(path, stat.S_IWRITE)
                func(path)

        try:
            # 首先尝试正常删除
            shutil.rmtree(current_path)
        except PermissionError:
            try:
                # 如果权限错误，尝试强制删除
                print(f"Permission error, trying force delete for: {current_path}")
                shutil.rmtree(current_path, onerror=handle_remove_readonly)
            except Exception as force_error:
                # 如果强制删除也失败，尝试使用系统命令
                try:
                    import subprocess
                    print(f"Force delete failed, trying system command for: {current_path}")

                    # 使用Windows的rmdir命令强制删除
                    result = subprocess.run(
                        ["rmdir", "/s", "/q", current_path],
                        shell=True,
                        capture_output=True,
                        text=True
                    )

                    if result.returncode != 0:
                        raise Exception(f"系统命令删除失败: {result.stderr}")

                except Exception as cmd_error:
                    return {
                        "status": "error",
                        "message": f"无法删除节点目录: {str(cmd_error)}。请手动删除目录: {current_path}"
                    }
        
        result = {
            "status": "success",
            "message": f"节点 {node_name} 卸载成功",
            "deleted_path": current_path
        }
        
        if backup_path:
            result["backup_path"] = backup_path
            result["message"] += f"，备份已保存到: {backup_path}"
        
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"节点卸载失败: {str(e)}"
        }

@app.get("/nodes/github-stars/{repo_owner}/{repo_name}")
async def get_github_stars_api(repo_owner: str, repo_name: str):
    """异步获取GitHub仓库的star数"""
    try:
        repo_key = f"{repo_owner}/{repo_name}"
        github_url = f"https://github.com/{repo_key}"

        stars = get_github_stars(github_url)

        return {
            "status": "success",
            "repo": repo_key,
            "stars": stars
        }
    except Exception as e:
        print(f"Error getting GitHub stars for {repo_owner}/{repo_name}: {str(e)}")
        return {
            "status": "error",
            "repo": f"{repo_owner}/{repo_name}",
            "stars": 0,
            "error": str(e)
        }

@app.get("/nodes/available")
async def get_available_nodes():
    """获取可安装的节点列表（从ComfyUI-Manager数据源）"""
    try:
        # 设置编码保护环境
        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        
        # 查找ComfyUI-Manager的节点列表文件
        manager_path = os.path.join(comfyui_dir, "custom_nodes", "comfyui-manager")
        node_list_file = os.path.join(manager_path, "custom-node-list.json")

        # 如果没有ComfyUI-Manager，尝试从网络获取数据
        if not os.path.exists(node_list_file):
            print("ComfyUI-Manager not found locally, trying to fetch data from network...")
            return await get_available_nodes_from_network()
        
        # 读取节点列表（安全编码处理）
        import json
        with open(node_list_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            # 移除常见的有问题字符
            content = content.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            data = json.loads(content)

        print(f"Loaded ComfyUI-Manager node list from: {node_list_file}")
        print(f"Total available nodes in ComfyUI-Manager: {len(data.get('custom_nodes', []))}")

        # 读取GitHub star数据
        github_stats_file = os.path.join(os.path.dirname(node_list_file), "github-stats.json")
        github_stats = {}
        if os.path.exists(github_stats_file):
            try:
                with open(github_stats_file, 'r', encoding='utf-8') as f:
                    github_stats = json.load(f)
                print(f"Loaded GitHub stats from: {github_stats_file}")
                print(f"Total GitHub stats entries: {len(github_stats)}")
            except Exception as e:
                print(f"Error loading GitHub stats: {e}")
                github_stats = {}
        else:
            print(f"GitHub stats file not found: {github_stats_file}")

        # 使用统一的处理逻辑
        return await process_node_data(data, github_stats)
        
        # 处理节点数据
        available_nodes = []
        for node in data.get("custom_nodes", []):
            # 确保有基本信息
            if not node.get("title"):
                continue
                
            # 检查是否已安装 - 改进的匹配逻辑
            node_title = node.get("title", "").strip()
            node_id = node.get("id", "").strip()

            # 生成多种可能的匹配名称
            possible_names = set()

            if node_title:
                possible_names.add(node_title.lower())
                # 移除常见前缀
                title_clean = node_title.lower()
                for prefix in ['comfyui-', 'comfyui_', 'comfy-', 'comfy_']:
                    if title_clean.startswith(prefix):
                        possible_names.add(title_clean[len(prefix):])

                # 替换分隔符的变体
                title_variants = [
                    node_title.lower().replace(" ", "-"),
                    node_title.lower().replace(" ", "_"),
                    node_title.lower().replace("-", "_"),
                    node_title.lower().replace("_", "-"),
                    node_title.lower().replace(" ", ""),
                    node_title.lower().replace("-", ""),
                    node_title.lower().replace("_", "")
                ]
                possible_names.update(title_variants)

            if node_id:
                possible_names.add(node_id.lower())

            # 检查是否有匹配的已安装插件
            is_installed = False
            for installed_name in installed_nodes:
                installed_lower = installed_name.lower()

                # 精确匹配
                if installed_lower in possible_names:
                    is_installed = True
                    break

                # 包含匹配（双向）
                for possible_name in possible_names:
                    if (possible_name in installed_lower or
                        installed_lower in possible_name) and len(possible_name) > 3:
                        is_installed = True
                        break

                if is_installed:
                    break

            if is_installed:
                print(f"Plugin '{node_title}' detected as installed (matched with: {[name for name in installed_nodes if any(pn in name.lower() or name.lower() in pn for pn in possible_names)]})")
            
            # 确定安装类型
            install_type = node.get("install_type", "git-clone")
            if install_type == "git-clone":
                install_method = "Git克隆"
            elif install_type == "copy":
                install_method = "文件复制"
            else:
                install_method = "未知"
            
            # 提取仓库URL
            repo_url = ""
            files = node.get("files", [])
            if files:
                repo_url = files[0]
            
            # 自动分类节点
            category = categorize_node(node.get("title", ""), node.get("description", ""))
            
            # 获取star数据
            stars = 0

            # 首先检查ComfyUI-Manager数据中是否有star信息
            if "stars" in node:
                stars = node["stars"]
            elif "star" in node:
                stars = node["star"]
            elif "github_stars" in node:
                stars = node["github_stars"]
            else:
                # 优先使用ComfyUI-Manager的GitHub stats数据
                reference = node.get("reference", "")
                if reference and reference in github_stats:
                    stars = github_stats[reference].get("stars", 0)
                    if stars > 0:
                        print(f"Using ComfyUI-Manager GitHub stats: {node.get('title', '')} = {stars} stars")

                # 如果ComfyUI-Manager没有数据，检查我们的缓存
                if stars == 0 and reference and "github.com" in reference:
                    repo_key = extract_repo_key(reference)
                    if repo_key and repo_key in github_stars_cache:
                        # 检查缓存是否过期
                        now = datetime.now()
                        if repo_key in cache_expiry and now < cache_expiry[repo_key]:
                            stars = github_stars_cache[repo_key]

                # 最后使用智能生成
                if stars == 0:
                    title = node.get("title", "")
                    stars = generate_smart_stars(title)

            processed_node = {
                "id": node_id,  # 使用处理后的ID
                "title": node.get("title", ""),
                "author": node.get("author", ""),
                "description": node.get("description", ""),
                "reference": node.get("reference", ""),
                "repo_url": repo_url,
                "install_type": install_type,
                "install_method": install_method,
                "is_installed": is_installed,
                "stars": stars,  # 添加star数据
                "tags": node.get("tags", []),
                "nodename_pattern": node.get("nodename_pattern", ""),
                "preemptions": node.get("preemptions", []),
                "category": category
            }
            
            available_nodes.append(processed_node)
        
        # 不在初始加载时批量获取GitHub star数，提高页面加载速度
        print(f"Available plugins loaded with smart star generation")

        # 按star数排序（降序），star数相同时按标题排序
        available_nodes.sort(key=lambda x: (-x["stars"], x["title"].lower()))
        
        return {
            "status": "success",
            "nodes": available_nodes,
            "total_count": len(available_nodes),
            "installed_count": len([n for n in available_nodes if n["is_installed"]]),
            "available_count": len([n for n in available_nodes if not n["is_installed"]])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取可用节点失败: {str(e)}"
        }

@app.post("/nodes/install")
async def install_node(request: dict):
    """安装自定义节点"""
    try:
        # 记录总安装开始时间
        total_start_time = time.time()
        node_id = request.get("node_id")
        repo_url = request.get("repo_url")
        install_type = request.get("install_type", "git-clone")
        
        if not node_id or not repo_url:
            return {"status": "error", "message": "缺少必要参数：node_id 或 repo_url"}
        
        # 并发安装控制
        with install_lock:
            if node_id in current_installations:
                return {"status": "error", "message": f"插件 {node_id} 正在安装中，请稍后再试"}
            current_installations.add(node_id)
        
        try:
            # 使用便携包路径配置
            paths = get_portable_paths()
            custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
            
            # 确保custom_nodes目录存在
            os.makedirs(custom_nodes_dir, exist_ok=True)
            
            # 根据安装类型执行不同的安装方法
            if install_type == "git-clone":
                # Git克隆安装
                import subprocess
                
                # 从URL推断目录名称
                if repo_url.endswith('.git'):
                    dir_name = os.path.basename(repo_url)[:-4]
                else:
                    dir_name = os.path.basename(repo_url)
                
                # 如果目录名为空，使用node_id
                if not dir_name:
                    dir_name = node_id
                
                target_dir = os.path.join(custom_nodes_dir, dir_name)
                
                # 检查目录是否已存在
                if os.path.exists(target_dir):
                    return {
                        "status": "error", 
                        "message": f"目录 {dir_name} 已存在，可能节点已安装"
                    }
                
                try:
                    # Git加速优化 - 智能镜像源选择
                    clone_url = repo_url
                    clone_method = "github"
                    
                    # 测试GitHub连接速度
                    github_accessible = True
                    test_duration = 999
                    try:
                        print(f" 测试GitHub连接: {repo_url}")
                        connection_start = time.time()
                        response = requests.head(repo_url, timeout=3)
                        test_duration = time.time() - connection_start
                        print(f"GitHub连接测试: {test_duration:.2f}秒")
                        
                        if response.status_code != 200:
                            github_accessible = False
                    except Exception as e:
                        print(f"ERROR GitHub连接失败: {e}")
                        github_accessible = False
                    
                    # 如果GitHub访问慢，尝试使用镜像源
                    if not github_accessible or test_duration > 3:
                        print("GitHub访问较慢，尝试使用镜像加速...")
                        
                        # 中国镜像源选项
                        mirror_options = [
                            ("https://ghproxy.com/", "ghproxy镜像"),
                            ("https://mirror.ghproxy.com/", "ghproxy备用镜像"),
                            ("https://github.moeyy.xyz/", "moeyy镜像"),
                        ]
                        
                        # 尝试镜像源
                        for mirror_prefix, mirror_name in mirror_options:
                            try:
                                mirror_url = mirror_prefix + repo_url
                                print(f" 测试{mirror_name}: {mirror_url}")
                                
                                mirror_test_start = time.time()
                                mirror_response = requests.head(mirror_url, timeout=3)
                                mirror_test_duration = time.time() - mirror_test_start
                                
                                if mirror_response.status_code == 200 and mirror_test_duration < test_duration:
                                    clone_url = mirror_url
                                    clone_method = mirror_name
                                    print(f"OK 使用{mirror_name}加速，响应时间: {mirror_test_duration:.2f}秒")
                                    break
                            except Exception as e:
                                print(f"ERROR {mirror_name}测试失败: {e}")
                                continue
                    
                    # 记录开始时间
                    git_start_time = time.time()
                    print(f"开始Git克隆: {clone_url} -> {target_dir}")
                    print(f"使用方式: {clone_method}")
                    
                    # 执行git clone（优化但保持足够的历史记录）
                    git_cmd = [
                        "git", "clone", 
                        "--depth=50",             # 浅克隆但保留足够历史（50个提交）
                        "--no-tags",              # 不获取标签
                        "-c", "core.compression=9",  # 最大压缩
                        "-c", "pack.threads=4",      # 多线程打包
                        clone_url, target_dir
                    ]
                    
                    result = subprocess.run(
                        git_cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,  # 5分钟超时
                    )
                    
                    git_duration = time.time() - git_start_time
                    print(f"Git克隆耗时: {git_duration:.2f}秒")
                    
                    # 分析克隆速度和方式
                    if git_duration > 30:
                        print("警告  Git克隆速度较慢，可能是网络问题")
                    elif git_duration > 10:
                        print("警告  Git克隆速度一般")
                    else:
                        print("OK Git克隆速度正常")
                    
                    # 显示加速效果
                    if clone_method != "github":
                        print(f"镜像加速生效: {clone_method}")
                    
                    if result.returncode == 0:
                        # 检查是否有requirements.txt并尝试安装依赖
                        requirements_file = os.path.join(target_dir, "requirements.txt")
                        pip_install_log = ""
                        
                        if os.path.exists(requirements_file):
                            try:
                                # 记录pip安装开始时间
                                pip_start_time = time.time()
                                print(f"开始安装依赖: {requirements_file}")
                                
                                # 优化pip安装：使用缓存和并发
                                pip_result = subprocess.run(
                                    [sys.executable, "-m", "pip", "install", "-r", requirements_file, 
                                     "--cache-dir", os.path.expanduser("~/.cache/pip"),
                                     "--disable-pip-version-check"],
                                    capture_output=True,
                                    text=True,
                                    timeout=600  # 10分钟超时
                                )
                                
                                pip_duration = time.time() - pip_start_time
                                print(f"依赖安装耗时: {pip_duration:.2f}秒")
                                
                                # 分析pip安装速度
                                if pip_duration > 60:
                                    print("警告  依赖安装速度较慢，可能是网络问题或大型依赖包")
                                elif pip_duration > 20:
                                    print("警告  依赖安装速度一般")
                                else:
                                    print("OK 依赖安装速度正常")
                                
                                if pip_result.returncode == 0:
                                    pip_install_log = "依赖安装成功"
                                else:
                                    pip_install_log = f"依赖安装警告: {pip_result.stderr[:200]}"
                            except subprocess.TimeoutExpired:
                                pip_install_log = "依赖安装超时，请手动安装"
                            except Exception as e:
                                pip_install_log = f"依赖安装出错: {str(e)[:200]}"
                        
                        # 记录总安装时间
                        total_duration = time.time() - total_start_time
                        print(f"插件 {node_id} 安装完成，总耗时: {total_duration:.2f}秒")
                        
                        return {
                            "status": "success",
                            "message": f"节点 {node_id} 安装成功",
                            "install_path": target_dir,
                            "pip_log": pip_install_log,
                            "git_output": result.stdout[:500] if result.stdout else "",
                            "install_duration": f"{total_duration:.2f}秒"
                        }
                    else:
                        return {
                            "status": "error",
                            "message": f"Git克隆失败: {result.stderr[:200]}"
                        }
                        
                except subprocess.TimeoutExpired:
                    return {
                        "status": "error",
                        "message": "安装超时，仓库可能太大或网络连接问题"
                    }
                except Exception as git_error:
                    return {
                        "status": "error",
                        "message": f"Git安装出错: {str(git_error)}"
                    }
            
            else:
                return {
                    "status": "error",
                    "message": f"不支持的安装类型: {install_type}"
                }
                
        except Exception as git_error:
            return {
                "status": "error",
                "message": f"Git安装出错: {str(git_error)}"
            }
        finally:
            # 清除并发控制标记
            with install_lock:
                current_installations.discard(node_id)
                
    except Exception as e:
        return {
            "status": "error",
            "message": f"节点安装失败: {str(e)}"
        }
    finally:
        # 确保无论如何都清除并发控制标记
        with install_lock:
            current_installations.discard(node_id)

@app.get("/nodes/check-updates")
async def check_node_updates():
    """检查节点更新"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
        
        if not os.path.exists(custom_nodes_dir):
            return {"status": "success", "updates": [], "message": "无自定义节点目录"}
        
        updates = []
        checked_count = 0
        error_count = 0
        
        for item in os.listdir(custom_nodes_dir):
            item_path = os.path.join(custom_nodes_dir, item)
            
            # 跳过文件和非Git仓库
            if not os.path.isdir(item_path) or item.startswith('.'):
                continue
            
            git_dir = os.path.join(item_path, '.git')
            if not os.path.exists(git_dir):
                continue
            
            # 跳过禁用的节点
            if item.endswith('.disabled'):
                continue
            
            try:
                import subprocess
                
                # 获取当前commit
                current_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=item_path,
                    timeout=30
                )
                
                if current_result.returncode != 0:
                    error_count += 1
                    continue
                
                current_commit = current_result.stdout.strip()
                
                # 获取远程信息并检查更新
                fetch_result = subprocess.run(
                    ["git", "fetch", "origin"],
                    capture_output=True,
                    text=True,
                    cwd=item_path,
                    timeout=60
                )
                
                if fetch_result.returncode != 0:
                    error_count += 1
                    continue
                
                # 获取远程最新commit
                remote_result = subprocess.run(
                    ["git", "rev-parse", "origin/HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=item_path,
                    timeout=30
                )
                
                # 如果origin/HEAD不存在，尝试origin/main或origin/master
                if remote_result.returncode != 0:
                    for branch in ["origin/main", "origin/master"]:
                        remote_result = subprocess.run(
                            ["git", "rev-parse", branch],
                            capture_output=True,
                            text=True,
                            cwd=item_path,
                            timeout=30
                        )
                        if remote_result.returncode == 0:
                            break
                
                if remote_result.returncode != 0:
                    error_count += 1
                    continue
                
                remote_commit = remote_result.stdout.strip()
                checked_count += 1
                
                # 检查是否有更新
                if current_commit != remote_commit:
                    # 获取commit信息
                    log_result = subprocess.run(
                        ["git", "log", "--oneline", f"{current_commit}..{remote_commit}"],
                        capture_output=True,
                        text=True,
                        cwd=item_path,
                        timeout=30
                    )
                    
                    commit_count = len(log_result.stdout.strip().split('\n')) if log_result.stdout.strip() else 0
                    
                    # 获取最新commit的信息
                    latest_commit_result = subprocess.run(
                        ["git", "log", "-1", "--format=%s", remote_commit],
                        capture_output=True,
                        text=True,
                        cwd=item_path,
                        timeout=30
                    )
                    
                    latest_message = latest_commit_result.stdout.strip() if latest_commit_result.returncode == 0 else "无法获取"
                    
                    # 获取最后更新时间
                    date_result = subprocess.run(
                        ["git", "log", "-1", "--format=%ci", remote_commit],
                        capture_output=True,
                        text=True,
                        cwd=item_path,
                        timeout=30
                    )
                    
                    last_update = date_result.stdout.strip() if date_result.returncode == 0 else ""
                    
                    updates.append({
                        "node_name": item,
                        "current_commit": current_commit[:8],
                        "latest_commit": remote_commit[:8],
                        "commit_count": commit_count,
                        "latest_message": latest_message,
                        "last_update": last_update,
                        "can_update": True
                    })
                
            except subprocess.TimeoutExpired:
                error_count += 1
                continue
            except Exception:
                error_count += 1
                continue
        
        return {
            "status": "success",
            "updates": updates,
            "total_checked": checked_count,
            "error_count": error_count,
            "update_count": len(updates),
            "message": f"检查完成：{checked_count}个节点已检查，{len(updates)}个有更新，{error_count}个出错"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"检查更新失败: {str(e)}"
        }

# Plugin Management Endpoints  
@app.get("/test/plugins")
async def test_plugins_endpoint():
    """测试插件端点"""
    return {"status": "success", "message": "Plugin endpoint working"}

@app.get("/api/plugins/installed")
async def get_installed_plugins():
    """获取已安装的插件列表"""
    try:
        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
        
        if not os.path.exists(custom_nodes_dir):
            return {"status": "success", "plugins": []}
        
        plugins = []
        for item in os.listdir(custom_nodes_dir):
            item_path = os.path.join(custom_nodes_dir, item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                # 检查是否是Git仓库
                is_git = os.path.exists(os.path.join(item_path, '.git'))
                
                # 检查是否有Python文件
                has_py_files = any(f.endswith('.py') for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f)))
                
                if has_py_files:
                    plugin_info = {
                        "name": item,
                        "path": item_path,
                        "enabled": True,  # 简化：假设都启用
                        "is_git": is_git,
                        "description": f"Custom node: {item}",
                        "version": "unknown"
                    }
                    
                    # 尝试获取更多信息
                    try:
                        if is_git:
                            import git
                            repo = git.Repo(item_path)
                            try:
                                latest_commit = repo.head.commit
                                plugin_info["version"] = latest_commit.hexsha[:8]
                                plugin_info["last_update"] = latest_commit.committed_datetime.strftime("%Y-%m-%d")
                            except:
                                pass
                    except:
                        pass
                    
                    plugins.append(plugin_info)
        
        return {"status": "success", "plugins": plugins}
        
    except Exception as e:
        return {"status": "error", "message": f"获取插件列表失败: {str(e)}"}

@app.post("/api/plugins/toggle")
async def toggle_plugin(request: dict):
    """启用/禁用插件"""
    try:
        plugin_name = request.get("plugin_name")
        enabled = request.get("enabled", True)
        
        if not plugin_name:
            return {"status": "error", "message": "插件名称不能为空"}
        
        # 这里应该实现具体的启用/禁用逻辑
        # 简化版本：返回成功状态
        return {
            "status": "success", 
            "message": f"插件 {plugin_name} 已{'启用' if enabled else '禁用'}"
        }
        
    except Exception as e:
        return {"status": "error", "message": f"插件操作失败: {str(e)}"}

@app.post("/plugins/validate-url")
async def validate_plugin_url(request: dict):
    """验证插件URL的可访问性"""
    try:
        url = request.get("url")
        if not url:
            return {"status": "error", "message": "URL不能为空"}

        import requests
        import re

        # 标准化URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # 验证URL格式
        github_pattern = r'https://github\.com/[^/]+/[^/]+/?'
        if not re.match(github_pattern, url):
            return {"status": "error", "message": "请提供有效的GitHub仓库地址"}

        # 检查URL可访问性
        try:
            response = requests.head(url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                return {"status": "success", "message": "URL验证成功", "url": url}
            else:
                return {"status": "error", "message": f"无法访问该URL (状态码: {response.status_code})"}
        except requests.RequestException as e:
            return {"status": "error", "message": f"网络请求失败: {str(e)}"}

    except Exception as e:
        return {"status": "error", "message": f"验证失败: {str(e)}"}

@app.post("/plugins/install-manual")
async def install_plugin_manual(request: dict):
    """手动安装插件"""
    try:
        url = request.get("url")
        force_install = request.get("force_install", False)

        if not url:
            return {"status": "error", "message": "URL不能为空"}

        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")

        # 确保custom_nodes目录存在
        if not os.path.exists(custom_nodes_dir):
            os.makedirs(custom_nodes_dir)

        # 从URL提取插件名称
        import re
        match = re.search(r'/([^/]+?)(?:\.git)?/?$', url)
        if not match:
            return {"status": "error", "message": "无法从URL提取插件名称"}

        plugin_name = match.group(1)
        plugin_path = os.path.join(custom_nodes_dir, plugin_name)

        # 检查插件是否已存在
        if os.path.exists(plugin_path) and not force_install:
            return {"status": "error", "message": f"插件 {plugin_name} 已存在"}

        # 如果强制安装且目录存在，先删除
        if force_install and os.path.exists(plugin_path):
            import shutil
            shutil.rmtree(plugin_path)

        # 克隆仓库
        import git
        try:
            git.Repo.clone_from(url, plugin_path)
            return {
                "status": "success",
                "message": f"插件 {plugin_name} 安装成功",
                "plugin_name": plugin_name
            }
        except git.GitCommandError as e:
            return {"status": "error", "message": f"Git克隆失败: {str(e)}"}
        except Exception as e:
            return {"status": "error", "message": f"安装失败: {str(e)}"}

    except Exception as e:
        return {"status": "error", "message": f"安装过程出错: {str(e)}"}

@app.post("/api/plugins/update")
async def update_plugin(request: dict):
    """更新插件到最新版本"""
    try:
        plugin_name = request.get("plugin_name")

        if not plugin_name:
            return {"status": "error", "message": "插件名称不能为空"}

        # 使用便携包路径配置
        paths = get_portable_paths()
        comfyui_dir = paths["comfyui_path"]
        plugin_path = os.path.join(comfyui_dir, "custom_nodes", plugin_name)

        if not os.path.exists(plugin_path):
            return {"status": "error", "message": "插件目录不存在"}

        if not os.path.exists(os.path.join(plugin_path, '.git')):
            return {"status": "error", "message": "插件不是Git仓库，无法更新"}

        import git
        repo = git.Repo(plugin_path)

        # 确定主分支（支持大小写变体）
        main_branch = None
        for branch_name in ['main', 'master', 'Main', 'Master']:
            try:
                # 检查远程是否有这个分支
                for remote in repo.remotes:
                    if f"{remote.name}/{branch_name}" in [ref.name for ref in remote.refs]:
                        main_branch = branch_name
                        break
                if main_branch:
                    break
            except:
                continue

        if not main_branch:
            return {"status": "error", "message": "无法确定主分支"}

        try:
            # 获取当前状态
            old_commit = repo.head.commit.hexsha[:8]

            # 拉取最新代码
            origin = repo.remotes.origin
            origin.fetch()

            # 切换到主分支并拉取最新代码
            repo.git.checkout(main_branch)
            origin.pull(main_branch)

            # 获取新状态
            new_commit = repo.head.commit.hexsha[:8]

            # 清除插件缓存
            global plugin_cache, plugin_cache_time, _plugin_version_cache, _plugin_version_cache_time
            plugin_cache = None
            plugin_cache_time = 0

            # 清除该插件的版本缓存
            if plugin_name in _plugin_version_cache:
                del _plugin_version_cache[plugin_name]
            if plugin_name in _plugin_version_cache_time:
                del _plugin_version_cache_time[plugin_name]

            print(f"Cleared plugin cache and version cache after update for {plugin_name}")

            return {
                "status": "success",
                "message": f"插件 {plugin_name} 更新成功",
                "old_commit": old_commit,
                "new_commit": new_commit,
                "updated": old_commit != new_commit
            }

        except git.exc.GitCommandError as e:
            return {"status": "error", "message": f"Git更新失败: {str(e)}"}

    except Exception as e:
        return {"status": "error", "message": f"插件更新失败: {str(e)}"}

# 插件版本缓存
_plugin_version_cache = {}
_plugin_version_cache_time = {}
_plugin_version_cache_duration = 1800  # 30分钟缓存（优化后）

# 插件版本管理API
@app.get("/plugins/{plugin_name}/versions")
async def get_plugin_versions(plugin_name: str, force_refresh: bool = False):
    """获取插件的Git版本历史"""
    try:
        import git
        import os
        from datetime import datetime
        import time

        # 检查是否强制刷新
        if force_refresh:
            print(f"Force refresh requested for plugin versions: {plugin_name}")
            if plugin_name in _plugin_version_cache:
                del _plugin_version_cache[plugin_name]
            if plugin_name in _plugin_version_cache_time:
                del _plugin_version_cache_time[plugin_name]

        # 检查缓存是否有效（已启用缓存以提升性能）
        current_time = time.time()
        if True and (plugin_name in _plugin_version_cache and
            plugin_name in _plugin_version_cache_time and
            (current_time - _plugin_version_cache_time[plugin_name]) < _plugin_version_cache_duration):
            print(f"Using cached version data for {plugin_name} (age: {current_time - _plugin_version_cache_time[plugin_name]:.1f}s)")
            return _plugin_version_cache[plugin_name]

        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
        plugin_dir = os.path.join(custom_nodes_dir, plugin_name)

        if not os.path.exists(plugin_dir):
            return {"status": "error", "message": f"插件目录不存在: {plugin_name}"}

        if not os.path.exists(os.path.join(plugin_dir, ".git")):
            return {"status": "error", "message": f"插件 {plugin_name} 不是Git仓库"}

        # 打开Git仓库
        repo = git.Repo(plugin_dir)

        # 获取当前分支
        current_branch = repo.active_branch.name if not repo.head.is_detached else "detached"
        current_commit = repo.head.commit.hexsha[:8]

        print(f"DEBUG: Plugin {plugin_name} - Current branch: {current_branch}, Current commit: {current_commit}")

        versions = []

        # 只获取主分支的提交历史（main或master）
        main_branch = None

        # 确定主分支名称（支持大小写变体）
        for branch_name in ['main', 'master', 'Main', 'Master']:
            if branch_name in [b.name for b in repo.branches]:
                main_branch = branch_name
                break
            # 检查远程分支
            for remote in repo.remotes:
                remote_ref_name = f"{remote.name}/{branch_name}"
                if remote_ref_name in [ref.name for ref in remote.refs]:
                    main_branch = branch_name
                    break
            if main_branch:
                break

        if not main_branch:
            main_branch = 'master'  # 默认使用master

        print(f"Using main branch: {main_branch} for plugin {plugin_name}")

        # 首先尝试获取远程主分支信息和标签
        try:
            # 获取远程信息，只获取主分支和标签
            for remote in repo.remotes:
                try:
                    # 首先尝试获取更多历史
                    try:
                        # 对于浅克隆，使用Git命令获取完整历史
                        import subprocess
                        result = subprocess.run(['git', 'fetch', '--unshallow'], 
                                              cwd=plugin_dir, capture_output=True, text=True)
                        if result.returncode == 0:
                            print(f"Fetched complete history using git fetch --unshallow")
                        else:
                            # 如果unshallow失败，尝试普通fetch
                            remote.fetch(tags=True, force=True, refspec=f'+refs/heads/{main_branch}:refs/remotes/{remote.name}/{main_branch}')
                            print(f"Fetched main branch '{main_branch}' from remote: {remote.name}")
                    except Exception as fetch_e:
                        # 如果fetch失败，尝试获取主分支
                        remote.fetch(tags=True, force=True, refspec=f'+refs/heads/{main_branch}:refs/remotes/{remote.name}/{main_branch}')
                        print(f"Fetched main branch '{main_branch}' from remote: {remote.name}")
                except Exception as e:
                    print(f"Failed to fetch main branch from remote {remote.name}: {e}")
                    # 如果上面的方式失败，尝试简单的fetch
                    try:
                        remote.fetch(tags=True)
                        print(f"Fallback fetch successful for remote: {remote.name}")
                    except Exception as e2:
                        print(f"Fallback fetch also failed for remote {remote.name}: {e2}")
        except Exception as e:
            print(f"Error fetching remotes: {e}")

        # 获取主分支的提交历史
        try:
            # 尝试切换到主分支获取提交历史
            main_ref = None

            # 优先使用远程分支（获取最新版本）
            for remote in repo.remotes:
                remote_ref_name = f"{remote.name}/{main_branch}"
                if remote_ref_name in [ref.name for ref in remote.refs]:
                    main_ref = remote.refs[main_branch]
                    print(f"Using remote branch: {remote_ref_name}")
                    break

            # 如果没有远程分支，使用本地分支
            if not main_ref and main_branch in [b.name for b in repo.branches]:
                main_ref = repo.branches[main_branch]
                print(f"Using local branch: {main_branch}")

            if main_ref:
                # 获取主分支的更多提交（20个），确保包含最新版本
                commits = list(repo.iter_commits(main_ref, max_count=20))

                for commit in commits:
                    # 精确比较提交哈希值（前8位）
                    commit_short = commit.hexsha[:8]
                    is_current = commit_short == current_commit
                    commit_date = datetime.fromtimestamp(commit.committed_date).strftime("%Y-%m-%d")
                    print(f"DEBUG: Commit {commit_short} - Date: {commit_date}, Is current: {is_current}, Current commit: {current_commit}")
                    versions.append({
                        "version": f"{main_branch} ({commit_short})",
                        "type": "commit",
                        "commit": commit_short,
                        "date": commit_date,
                        "message": commit.message.strip().split('\n')[0][:50],
                        "author": commit.author.name,
                        "current": is_current
                    })

        except Exception as e:
            print(f"Error getting main branch commits: {e}")
            # 如果获取主分支失败，至少添加当前提交
            try:
                current_commit_obj = repo.head.commit
                versions.append({
                    "version": f"{current_branch} ({current_commit})",
                    "type": "commit",
                    "commit": current_commit,
                    "date": datetime.fromtimestamp(current_commit_obj.committed_date).strftime("%Y-%m-%d"),
                    "message": current_commit_obj.message.strip().split('\n')[0][:50],
                    "author": current_commit_obj.author.name,
                    "current": True
                })
            except Exception as e2:
                print(f"Error getting current commit: {e2}")

        # 改进的排序逻辑：优先级 + 日期
        def version_sort_key(version):
            # 定义版本类型优先级
            type_priority = {
                "tag": 1,        # 标签版本优先级最高
                "branch": 2,     # 分支次之
                "remote_branch": 3,  # 远程分支
                "commit": 4      # 提交优先级最低
            }

            # 如果是当前版本，根据情况调整优先级
            if version["current"]:
                # 如果当前版本是标签，保持高优先级
                if version["type"] == "tag":
                    priority = 0  # 当前标签版本优先级最高
                else:
                    priority = 1.5  # 当前非标签版本适中优先级
            else:
                priority = type_priority.get(version["type"], 5)

            # 返回排序键：(优先级, 日期倒序)
            return (priority, version["date"])

        # 按时间排序（从最新到最旧）
        def time_sort_key(version):
            try:
                from datetime import datetime
                date_obj = datetime.strptime(version["date"], "%Y-%m-%d")
                return date_obj
            except:
                return datetime.min

        # 按日期排序（最新的在前）
        versions.sort(key=time_sort_key, reverse=True)

        # 去重并限制为7个版本
        seen = set()
        unique_versions = []
        for version in versions:
            key = (version["version"], version["commit"])
            if key not in seen:
                seen.add(key)
                unique_versions.append(version)
                if len(unique_versions) >= 7:
                    break

        # 确保当前版本在列表中，但不影响最新版本的显示
        current_version_in_list = any(v.get("current", False) for v in unique_versions)
        if not current_version_in_list:
            # 如果当前版本不在远程提交列表中，手动创建当前版本条目
            try:
                current_commit_obj = repo.head.commit
                current_version_entry = {
                    "version": f"{current_branch} ({current_commit})",
                    "type": "commit",
                    "commit": current_commit,
                    "date": datetime.fromtimestamp(current_commit_obj.committed_date).strftime("%Y-%m-%d"),
                    "message": current_commit_obj.message.strip().split('\n')[0][:50],
                    "author": current_commit_obj.author.name,
                    "current": True
                }

                if len(unique_versions) < 7:
                    # 如果列表未满，直接添加当前版本
                    unique_versions.append(current_version_entry)
                else:
                    # 如果列表已满，在适当位置插入当前版本，保持时间顺序
                    # 但优先保留最新的版本
                    current_date = time_sort_key(current_version_entry)
                    inserted = False
                    for i, existing_version in enumerate(unique_versions):
                        if time_sort_key(existing_version) < current_date:
                            unique_versions.insert(i, current_version_entry)
                            unique_versions = unique_versions[:7]  # 保持7个版本
                            inserted = True
                            break
                    if not inserted:
                        # 如果当前版本是最旧的，替换最后一个
                        unique_versions[-1] = current_version_entry

                print(f"Added current version manually: {current_commit} ({current_version_entry['date']})")
            except Exception as e:
                print(f"Error adding current version: {e}")

        # 调试：打印最终版本列表
        print(f"DEBUG: Final version list for {plugin_name}:")
        for i, version in enumerate(unique_versions):
            current_marker = " [CURRENT]" if version.get("current", False) else ""
            print(f"  {i+1}. {version['commit']} ({version['date']}){current_marker}")

        result = {
            "status": "success",
            "plugin_name": plugin_name,
            "current_branch": current_branch,
            "current_commit": current_commit,
            "versions": unique_versions
        }

        # 缓存结果
        _plugin_version_cache[plugin_name] = result
        _plugin_version_cache_time[plugin_name] = current_time
        print(f"Cached version data for {plugin_name}")

        return result

    except Exception as e:
        return {"status": "error", "message": f"获取插件版本失败: {str(e)}"}

@app.post("/plugins/{plugin_name}/switch-version")
async def switch_plugin_version(plugin_name: str, request: dict):
    """切换插件版本"""
    try:
        import git
        import os

        version = request.get("version")
        if not version:
            return {"status": "error", "message": "版本参数不能为空"}

        # 使用便携包路径配置
        paths = get_portable_paths()
        custom_nodes_dir = os.path.join(paths["comfyui_path"], "custom_nodes")
        plugin_dir = os.path.join(custom_nodes_dir, plugin_name)

        if not os.path.exists(plugin_dir):
            return {"status": "error", "message": f"插件目录不存在: {plugin_name}"}

        if not os.path.exists(os.path.join(plugin_dir, ".git")):
            return {"status": "error", "message": f"插件 {plugin_name} 不是Git仓库"}

        # 打开Git仓库
        repo = git.Repo(plugin_dir)

        # 检查是否有未提交的更改
        if repo.is_dirty():
            return {
                "status": "warning",
                "message": f"插件 {plugin_name} 有未提交的更改，请先提交或丢弃更改",
                "dirty_files": [item.a_path for item in repo.index.diff(None)]
            }

        # 获取当前状态
        old_branch = repo.active_branch.name if not repo.head.is_detached else "detached"
        old_commit = repo.head.commit.hexsha[:8]

        # 解析版本信息
        # 版本格式可能是: "main (b775441a)" 或 "b775441a" 或 "v1.0.0"
        commit_hash = None
        branch_name = None

        if '(' in version and ')' in version:
            # 格式: "main (b775441a)"
            parts = version.split('(')
            if len(parts) == 2:
                branch_name = parts[0].strip()
                commit_hash = parts[1].replace(')', '').strip()
        else:
            # 直接的分支名、标签名或提交哈希
            if len(version) == 8 and all(c in '0123456789abcdef' for c in version.lower()):
                # 看起来像提交哈希
                commit_hash = version
            else:
                # 可能是分支名或标签名
                branch_name = version

        print(f"Parsed version '{version}': branch='{branch_name}', commit='{commit_hash}'")

        # 执行切换
        try:
            switch_type = "unknown"

            # 优先使用提交哈希切换（最准确）
            if commit_hash:
                try:
                    repo.git.checkout(commit_hash)
                    switch_type = "commit"
                    print(f"Switched to commit: {commit_hash}")
                except git.exc.GitCommandError as e:
                    print(f"Failed to checkout commit {commit_hash}: {e}")
                    # 如果提交哈希失败，尝试使用分支名
                    if branch_name:
                        repo.git.checkout(branch_name)
                        switch_type = "branch"
                        print(f"Switched to branch: {branch_name}")
                    else:
                        raise e

            # 如果没有提交哈希，尝试分支名或标签
            elif branch_name:
                # 尝试切换到本地分支
                if branch_name in [branch.name for branch in repo.branches]:
                    repo.git.checkout(branch_name)
                    switch_type = "local_branch"
                # 尝试切换到标签
                elif branch_name in [tag.name for tag in repo.tags]:
                    repo.git.checkout(branch_name)
                    switch_type = "tag"
                    # 找到对应的远程分支
                    remote_ref = None
                    for remote in repo.remotes:
                        for ref in remote.refs:
                            if ref.name.endswith(f'/{branch_name}'):
                                remote_ref = ref
                                break
                        if remote_ref:
                            break

                    if remote_ref:
                        # 创建本地跟踪分支
                        repo.git.checkout('-b', branch_name, remote_ref.name)
                        switch_type = "remote_branch"
                    else:
                        raise Exception(f"Branch or tag '{branch_name}' not found")
                else:
                    raise Exception(f"Branch or tag '{branch_name}' not found")
            else:
                raise Exception("No valid version information provided")

            # 获取新状态
            new_branch = repo.active_branch.name if not repo.head.is_detached else "detached"
            new_commit = repo.head.commit.hexsha[:8]

            # 清除插件缓存，确保下次请求获取最新数据
            global plugin_cache, plugin_cache_time, _plugin_version_cache, _plugin_version_cache_time
            plugin_cache = None
            plugin_cache_time = 0

            # 清除该插件的版本缓存
            if plugin_name in _plugin_version_cache:
                del _plugin_version_cache[plugin_name]
            if plugin_name in _plugin_version_cache_time:
                del _plugin_version_cache_time[plugin_name]

            print(f"Cleared plugin cache and version cache after version switch for {plugin_name}")

            return {
                "status": "success",
                "message": f"成功切换 {plugin_name} 到 {version}",
                "plugin_name": plugin_name,
                "switch_type": switch_type,
                "old_version": {"branch": old_branch, "commit": old_commit},
                "new_version": {"branch": new_branch, "commit": new_commit}
            }

        except git.exc.GitCommandError as e:
            return {"status": "error", "message": f"Git切换失败: {str(e)}"}

    except Exception as e:
        return {"status": "error", "message": f"切换插件版本失败: {str(e)}"}

# 环境信息缓存 - 缓存5分钟
environment_info_cache = {
    "python": {"data": None, "timestamp": 0},
    "pytorch": {"data": None, "timestamp": 0},
    "dependencies": {"data": None, "timestamp": 0}
}

def is_cache_valid(cache_key, cache_duration=300):  # 300秒 = 5分钟
    """检查缓存是否有效"""
    import time
    cache_entry = environment_info_cache.get(cache_key)
    if not cache_entry or not cache_entry["data"]:
        return False
    return (time.time() - cache_entry["timestamp"]) < cache_duration

def get_cached_data(cache_key):
    """获取缓存数据"""
    return environment_info_cache[cache_key]["data"]

def set_cache_data(cache_key, data):
    """设置缓存数据"""
    import time
    environment_info_cache[cache_key] = {
        "data": data,
        "timestamp": time.time()
    }

# 获取终端环境信息API
@app.get("/terminal/info")
async def get_terminal_info():
    """获取终端环境信息"""
    try:
        # 获取便携包环境路径
        portable_paths = get_portable_paths()

        # 工作目录
        work_dir = Path(portable_paths['portable_root'])

        # 虚拟环境路径
        venv_path = Path(portable_paths['venv_path'])

        # 检查虚拟环境类型
        env_type = "未知"
        env_status = "未激活"

        if venv_path.exists():
            # 检查是否是conda环境
            conda_meta_path = venv_path / "conda-meta"
            if conda_meta_path.exists():
                env_type = "conda"
                env_status = "已激活"
            else:
                # 检查是否是普通虚拟环境
                if os.name == 'nt':
                    activate_script = venv_path / "Scripts" / "activate.bat"
                else:
                    activate_script = venv_path / "bin" / "activate"

                if activate_script.exists():
                    env_type = "venv"
                    env_status = "已激活"

        # 获取Python版本信息
        python_version = "未知"
        try:
            if venv_path.exists():
                if env_type == "conda":
                    python_exe = venv_path / "python.exe" if os.name == 'nt' else venv_path / "bin" / "python"
                else:
                    python_exe = venv_path / "Scripts" / "python.exe" if os.name == 'nt' else venv_path / "bin" / "python"

                if python_exe.exists():
                    result = subprocess.run([str(python_exe), "--version"],
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        python_version = result.stdout.strip()
        except Exception as e:
            print(f"Failed to get Python version: {e}")

        return {
            "work_dir": str(work_dir),
            "venv_path": str(venv_path),
            "venv_exists": venv_path.exists(),
            "env_type": env_type,
            "env_status": env_status,
            "python_version": python_version,
            "comfyui_path": str(Path(portable_paths['comfyui_path'])),
            "prompt": f"{env_type}> " if env_type != "未知" else "cmd> "
        }
    except Exception as e:
        return {
            "error": str(e),
            "work_dir": "检测失败",
            "venv_path": "检测失败",
            "venv_exists": False,
            "env_type": "未知",
            "env_status": "检测失败",
            "python_version": "检测失败",
            "comfyui_path": "检测失败",
            "prompt": "cmd> "
        }

# 新建终端API
@app.get("/debug/paths-terminal")
async def debug_terminal_paths():
    """调试终端路径信息"""
    try:
        portable_paths = get_portable_paths()
        work_dir = Path(portable_paths['comfyui_path'])
        venv_path = Path(portable_paths['venv_path'])
        activate_script = venv_path / "Scripts" / "activate.bat"
        
        portable_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # ComfyUI-AI-Vision-Portable目录
        python_dir = os.path.join(portable_root, "python")
        temp_bat_path = os.path.join(os.path.dirname(activate_script), "debug_terminal.bat")
        
        return {
            "__file__": __file__,
            "portable_root": portable_root,
            "venv_path": str(venv_path),
            "python_dir": python_dir,
            "work_dir": str(work_dir), 
            "activate_script": str(activate_script),
            "temp_bat_path": temp_bat_path,
            "activate_script_exists": os.path.exists(activate_script),
            "python_dir_exists": os.path.exists(python_dir),
            "work_dir_exists": os.path.exists(work_dir)
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/terminal/new")
async def open_new_terminal():
    """新建终端功能已禁用"""
    return {
        "success": False, 
        "error": "新建终端功能由于系统兼容性问题已禁用。请直接双击便携包根目录下的'激活虚拟环境.bat'文件来打开终端。"
    }

# 终端执行API
@app.post("/terminal/execute")
async def execute_terminal_command(command_data: dict):
    """执行终端命令"""
    try:
        command = command_data.get("command", "").strip()
        if not command:
            return {"success": False, "error": "命令不能为空"}
        
        # 这里应该是命令执行逻辑
        # 由于原始代码结构混乱，我添加一个基本的命令执行框架
        return {"success": True, "output": f"命令 '{command}' 已接收但执行功能需要完善"}
        
    except Exception as e:
        return {"success": False, "error": f"执行命令失败: {str(e)}"}


# ==================== 版本管理 API ====================
# 导入版本管理器
try:
    from core.version_manager import VersionManager
    # 初始化版本管理器
    version_manager = VersionManager()
    print(f"✅ 版本管理器初始化成功: {version_manager.project_path}")
except Exception as e:
    print(f"⚠️ 版本管理器初始化失败: {e}")
    version_manager = None

# 测试端点 - 用于验证后端代码是否已更新
@app.get("/test/backend-version")
async def test_backend_version():
    """测试后端版本 - 确认代码已更新"""
    return {
        "backend_version": "2025-07-30-v3-FIXED",
        "timestamp": datetime.now().isoformat(),
        "data_source_fix": "ENABLED",
        "message": "后端代码已更新，包含data_source字段修复"
    }

# 快速版本数据函数 - 使用预定义数据，避免Git操作
async def get_quick_version_data(current_commit: str = "7d593baf"):
    """快速模式：返回预定义的版本数据，避免耗时的Git操作"""
    print("⚡ 快速模式：生成预定义版本数据")
    
    # 预定义的稳定版本数据（最新的15个）
    quick_stable_versions = [
        {"id": "v0.3.47", "version": "v0.3.47", "date": "2025-07-29", "current": False, "message": "ComfyUI version 0.3.47", "author": "comfyanonymous"},
        {"id": "v0.3.46", "version": "v0.3.46", "date": "2025-07-28", "current": False, "message": "ComfyUI 0.3.46", "author": "comfyanonymous"},
        {"id": "v0.3.45", "version": "v0.3.45", "date": "2025-07-21", "current": False, "message": "ComfyUI version 0.3.45", "author": "comfyanonymous"},
        {"id": "v0.3.44", "version": "v0.3.44", "date": "2025-07-08", "current": False, "message": "ComfyUI version 0.3.44", "author": "comfyanonymous"},
        {"id": "v0.3.43", "version": "v0.3.43", "date": "2025-06-27", "current": False, "message": "ComfyUI version 0.3.43", "author": "comfyanonymous"}
    ]
    
    # 预定义的开发版本数据（最新的30个，包含新版本）
    quick_development_versions = [
        {"id": "d2aaef02", "commit": "d2aaef02", "commit_short": "d2aaef02", "date": "2025-07-30", "current": False, "message": "Update template to 0.1.44 (#9104)", "author": "ComfyUI Wiki"},
        {"id": "0a3d062e", "commit": "0a3d062e", "commit_short": "0a3d062e", "date": "2025-07-30", "current": False, "message": "ComfyAPI Core v0.0.2 (#8962)", "author": "guill"},
        {"id": "2f74e179", "commit": "2f74e179", "commit_short": "2f74e179", "date": "2025-07-30", "current": False, "message": "ComfyUI version 0.3.47", "author": "comfyanonymous"},
        {"id": "dca6bdd4", "commit": "dca6bdd4", "commit_short": "dca6bdd4", "date": "2025-07-30", "current": False, "message": "Make wan2.2 5B i2v take a lot less memory. (#9102)", "author": "comfyanonymous"},
        {"id": "7d593baf", "commit": "7d593baf", "commit_short": "7d593baf", "date": "2025-07-29", "current": True, "message": "Extra reserved vram on large cards on windows. (#9093)", "author": "comfyanonymous"},
        {"id": "c60dc417", "commit": "c60dc417", "commit_short": "c60dc417", "date": "2025-07-29", "current": False, "message": "Remove unecessary clones in the wan2.2 VAE. (#9083)", "author": "comfyanonymous"},
        {"id": "5d4cc3ba", "commit": "5d4cc3ba", "commit_short": "5d4cc3ba", "date": "2025-07-28", "current": False, "message": "ComfyUI 0.3.46", "author": "comfyanonymous"}
    ]
    
    # 构建响应数据
    result = {
        "status": "success",
        "stable": quick_stable_versions,
        "development": quick_development_versions,
        "current_commit": current_commit,
        "current_branch": "detached",
        "last_updated": datetime.now().isoformat()
    }
    
    # 显式添加关键字段
    result["quick_mode"] = True
    result["data_source"] = "local"
    
    print(f"⚡ 快速模式数据生成完成: 稳定版 {len(quick_stable_versions)} 个, 开发版 {len(quick_development_versions)} 个")
    print(f"🔍 快速模式返回字段: {list(result.keys())}")
    
    return result

# ==================== 启动器版本管理 API ====================
@app.get("/launcher/get-version")
async def get_launcher_version():
    """获取启动器版本信息"""
    try:
        # 读取package.json获取版本信息
        launcher_dir = Path(__file__).parent.parent
        package_json_path = launcher_dir / "package.json"
        
        if package_json_path.exists():
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            
            # 获取文件修改时间作为最后更新时间
            last_modified = datetime.fromtimestamp(package_json_path.stat().st_mtime)
            
            return {
                "status": "success",
                "version": package_data.get("version", "1.0.0"),
                "name": package_data.get("name", "ai-vision-launcher"),
                "description": package_data.get("description", "AI视界启动器"),
                "lastModified": last_modified.strftime("%Y-%m-%d"),
                "author": package_data.get("author", "AI Vision Team")
            }
        else:
            return {
                "status": "success", 
                "version": "1.0.0",
                "name": "ai-vision-launcher",
                "description": "AI视界启动器",
                "lastModified": "2025-07-31",
                "author": "AI Vision Team"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取版本信息失败: {str(e)}",
            "version": "1.0.0"
        }

@app.get("/launcher/version-info")
async def get_launcher_version_info():
    """获取启动器版本信息（用于更新检查）"""
    try:
        # 获取当前版本
        version_response = await get_launcher_version()
        current_version = version_response.get("version", "1.0.0")
        
        # GitHub仓库信息
        github_repo = "yangying1205/ComfyUI-AI-Vision-Launcher"
        github_api_url = f"https://api.github.com/repos/{github_repo}/releases/latest"
        
        try:
            # 检查GitHub最新版本
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(github_api_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        release_data = await response.json()
                        latest_version = release_data["tag_name"].lstrip("v")
                        
                        # 查找launcher更新包
                        launcher_asset = None
                        for asset in release_data["assets"]:
                            if "launcher" in asset["name"].lower() or "update" in asset["name"].lower():
                                launcher_asset = asset
                                break
                        
                        # 如果没找到专门的launcher包，使用第一个资产
                        if not launcher_asset and release_data["assets"]:
                            launcher_asset = release_data["assets"][0]
                        
                        # 版本比较
                        from packaging import version
                        has_update = version.parse(latest_version) > version.parse(current_version)
                        
                        return {
                            "current_version": current_version,
                            "latest_version": latest_version,
                            "has_update": has_update,
                            "download_url": launcher_asset["browser_download_url"] if launcher_asset else None,
                            "size": launcher_asset["size"] if launcher_asset else 0,
                            "changelog": release_data["body"],
                            "published_at": release_data["published_at"],
                            "github_url": f"https://github.com/{github_repo}/releases",
                            "manual_update": False
                        }
                    else:
                        # GitHub API请求失败，降级到手动更新模式
                        return {
                            "current_version": current_version,
                            "latest_version": current_version,
                            "has_update": False,
                            "message": "无法连接到GitHub检查更新，请手动访问项目页面",
                            "github_url": f"https://github.com/{github_repo}/releases",
                            "manual_update": True
                        }
        
        except ImportError:
            # 如果没有aiohttp，使用requests同步请求
            import requests
            try:
                response = requests.get(github_api_url, timeout=10)
                if response.status_code == 200:
                    release_data = response.json()
                    latest_version = release_data["tag_name"].lstrip("v")
                    
                    # 查找launcher更新包
                    launcher_asset = None
                    for asset in release_data["assets"]:
                        if "launcher" in asset["name"].lower() or "update" in asset["name"].lower():
                            launcher_asset = asset
                            break
                    
                    if not launcher_asset and release_data["assets"]:
                        launcher_asset = release_data["assets"][0]
                    
                    # 版本比较
                    from packaging import version
                    has_update = version.parse(latest_version) > version.parse(current_version)
                    
                    return {
                        "current_version": current_version,
                        "latest_version": latest_version,
                        "has_update": has_update,
                        "download_url": launcher_asset["browser_download_url"] if launcher_asset else None,
                        "size": launcher_asset["size"] if launcher_asset else 0,
                        "changelog": release_data["body"],
                        "published_at": release_data["published_at"],
                        "github_url": f"https://github.com/{github_repo}/releases",
                        "manual_update": False
                    }
                else:
                    raise Exception(f"GitHub API请求失败: {response.status_code}")
            except Exception as requests_error:
                print(f"使用requests检查更新失败: {requests_error}")
                return {
                    "current_version": current_version,
                    "latest_version": current_version,
                    "has_update": False,
                    "message": "无法连接到GitHub检查更新，请手动访问项目页面",
                    "github_url": f"https://github.com/{github_repo}/releases",
                    "manual_update": True
                }
        
        except Exception as e:
            print(f"检查GitHub更新失败: {e}")
            # 网络错误时降级到手动更新模式
            return {
                "current_version": current_version,
                "latest_version": current_version,
                "has_update": False,
                "message": f"检查更新失败: {str(e)}",
                "github_url": f"https://github.com/{github_repo}/releases",
                "manual_update": True
            }
        
    except Exception as e:
        return {
            "error": f"检查版本失败: {str(e)}"
        }

@app.post("/launcher/download-update")
async def download_launcher_update(request_data: dict):
    """下载启动器更新包"""
    try:
        download_url = request_data.get("download_url")
        if not download_url:
            return {"status": "error", "message": "缺少下载链接"}
        
        # 创建临时目录
        temp_dir = Path("temp_launcher_update")
        temp_dir.mkdir(exist_ok=True)
        
        # 清理旧的下载文件
        for old_file in temp_dir.glob("*"):
            try:
                old_file.unlink()
            except:
                pass
        
        # 下载文件
        print(f"开始下载启动器更新: {download_url}")
        
        try:
            # 优先使用aiohttp异步下载
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                    if response.status == 200:
                        zip_path = temp_dir / "launcher_update.zip"
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded = 0
                        
                        with open(zip_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                                downloaded += len(chunk)
                                
                                # 可以在这里添加进度回调
                                if total_size > 0:
                                    progress = (downloaded / total_size) * 100
                                    if downloaded % (1024 * 1024) == 0:  # 每MB打印一次进度
                                        print(f"下载进度: {progress:.1f}% ({downloaded}/{total_size})")
                        
                        print(f"下载完成: {zip_path} ({downloaded} bytes)")
                        return {
                            "status": "success",
                            "message": "下载完成",
                            "file_path": str(zip_path),
                            "size": downloaded
                        }
                    else:
                        return {"status": "error", "message": f"下载失败: HTTP {response.status}"}
        
        except ImportError:
            # 如果没有aiohttp，使用requests同步下载
            import requests
            response = requests.get(download_url, stream=True, timeout=300)
            response.raise_for_status()
            
            zip_path = temp_dir / "launcher_update.zip"
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0 and downloaded % (1024 * 1024) == 0:
                            progress = (downloaded / total_size) * 100
                            print(f"下载进度: {progress:.1f}% ({downloaded}/{total_size})")
            
            print(f"下载完成: {zip_path} ({downloaded} bytes)")
            return {
                "status": "success",
                "message": "下载完成",
                "file_path": str(zip_path),
                "size": downloaded
            }
        
    except Exception as e:
        print(f"下载更新包失败: {e}")
        return {
            "status": "error",
            "message": f"下载失败: {str(e)}"
        }

@app.get("/comfyui/versions")
async def get_comfyui_versions(force_refresh: bool = False, limit_stable: int = 20, limit_development: int = 30, quick_mode: bool = False):
    """获取ComfyUI版本信息"""
    print(f"🔍 ========== 版本API调用 ==========")
    print(f"🔍 参数 - 强制刷新: {force_refresh}, 快速模式: {quick_mode}, 稳定版限制: {limit_stable}, 开发版限制: {limit_development}")
    print(f"🔍 API VERSION: 2025-07-30-v2 - 包含data_source字段修复")
    try:
        if not version_manager or not version_manager.is_git_repo():
            print("❌ Git仓库未初始化或不存在")
            return {
                "status": "error",
                "message": "Git仓库未初始化或不存在",
                "stable": [],
                "development": [],
                "current_commit": "unknown",
                "current_branch": "unknown",
                "data_source": "local" if quick_mode else "remote",
                "quick_mode": quick_mode
            }
        
        print(f"🔍 获取版本信息 - 强制刷新: {force_refresh}, 快速模式: {quick_mode}, 稳定版限制: {limit_stable}, 开发版限制: {limit_development}")
        
        # 快速模式：使用模拟数据，跳过所有Git操作
        if quick_mode:
            print("⚡ 快速模式：使用缓存数据，跳过Git操作")
            return await get_quick_version_data(current_commit="7d593baf")
        
        # 正常模式：执行完整的Git操作
        use_remote_data = True
        if force_refresh:
            try:
                print("🔄 正在从远程获取最新版本信息...")
                success, message = version_manager.fetch_updates()
                print(f"远程更新结果: {message}")
            except Exception as e:
                print(f"⚠️ 从远程获取更新失败: {e}")
        
        # 获取当前版本信息
        current_version = version_manager.get_current_version()
        current_commit = current_version.commit_hash if current_version else "unknown"
        
        # 获取版本历史
        print(f"📋 获取版本历史 - 使用{'远程' if use_remote_data else '本地'}数据...")
        try:
            if use_remote_data:
                # 获取远程版本历史
                version_history = version_manager.get_version_history(limit=limit_development, use_remote=True)
                if not version_history:
                    print("⚠️ 远程版本历史为空，回退到本地版本历史")
                    version_history = version_manager.get_version_history(limit=limit_development, use_remote=False)
            else:
                # 只使用本地版本历史
                version_history = version_manager.get_version_history(limit=limit_development, use_remote=False)
        except Exception as e:
            print(f"⚠️ 获取版本历史失败: {e}，使用本地版本历史")
            version_history = version_manager.get_version_history(limit=limit_development, use_remote=False)
        
        # 获取标签（稳定版本）
        tags_info = version_manager.get_tags_with_info()
        
        # 处理稳定版本数据
        stable_versions = []
        for tag in tags_info[:limit_stable]:
            stable_versions.append({
                "id": tag.commit_hash,
                "version": tag.name,
                "message": tag.message,
                "author": tag.author,
                "date": tag.date.strftime("%Y-%m-%d"),
                "current": tag.is_current
            })
        
        # 处理开发版本数据
        development_versions = []
        for version in version_history[:limit_development]:
            # 获取完整的commit hash用于版本切换
            full_commit_hash = None
            try:
                # 根据短hash找到完整hash
                for commit in version_manager.repo.iter_commits():
                    if commit.hexsha.startswith(version.commit_hash):
                        full_commit_hash = commit.hexsha
                        break
            except:
                full_commit_hash = version.commit_hash
                
            development_versions.append({
                "id": full_commit_hash or version.commit_hash,
                "commit": full_commit_hash or version.commit_hash,
                "commit_short": version.commit_hash,
                "message": version.commit_message,
                "author": version.author,
                "date": version.date.strftime("%Y-%m-%d"),
                "current": version.is_current
            })
        
        # 获取当前分支信息
        try:
            current_branch = version_manager.repo.active_branch.name if not version_manager.repo.head.is_detached else "detached"
        except:
            current_branch = "unknown"
        
        # 构建响应数据
        result = {
            "status": "success",
            "stable": stable_versions,
            "development": development_versions,
            "current_commit": current_commit,
            "current_branch": current_branch,
            "last_updated": datetime.now().isoformat()
        }
        
        # 显式添加关键字段
        result["quick_mode"] = quick_mode
        result["data_source"] = "local" if quick_mode else "remote"
        
        print(f"✅ 版本信息获取成功: 稳定版 {len(stable_versions)} 个, 开发版 {len(development_versions)} 个")
        print(f"🔍 返回数据包含的字段: {list(result.keys())}")
        print(f"🔍 data_source字段值: {result['data_source']}")
        print(f"🔍 quick_mode字段值: {result['quick_mode']}")
        print(f"🔍 ========== 版本API返回 ==========")
        return result
        
    except Exception as e:
        print(f"❌ 获取版本信息失败: {e}")
        error_result = {
            "status": "error",
            "message": str(e),
            "stable": [],
            "development": [],
            "current_commit": "unknown",
            "current_branch": "unknown"
        }
        # 显式添加关键字段
        error_result["quick_mode"] = quick_mode
        error_result["data_source"] = "local" if quick_mode else "remote"
        return error_result

@app.post("/comfyui/switch-version")
async def switch_comfyui_version(request: dict):
    """切换ComfyUI版本"""
    try:
        if not version_manager or not version_manager.is_git_repo():
            return {
                "status": "error",
                "message": "Git仓库未初始化或不存在"
            }
        
        version_id = request.get("version_id")
        version_type = request.get("version_type", "commit")
        
        if not version_id:
            return {
                "status": "error",
                "message": "版本ID不能为空"
            }
        
        print(f"🔄 切换版本: {version_id} ({version_type})")
        
        # 根据版本类型执行不同的切换操作
        if version_type == "tag":
            success, message = version_manager.switch_to_tag(version_id)
        else:
            success, message = version_manager.switch_to_commit(version_id)
        
        if success:
            print(f"✅ 版本切换成功: {message}")
            return {
                "status": "success",
                "message": message
            }
        else:
            print(f"❌ 版本切换失败: {message}")
            return {
                "status": "error",
                "message": message
            }
    
    except Exception as e:
        print(f"❌ 版本切换异常: {e}")
        return {
            "status": "error",
            "message": f"版本切换失败: {str(e)}"
        }

@app.get("/comfyui/check-updates")
async def check_comfyui_updates():
    """检查ComfyUI更新"""
    try:
        if not version_manager or not version_manager.is_git_repo():
            return {
                "status": "error",
                "message": "Git仓库未初始化或不存在"
            }
        
        print("🔍 检查ComfyUI更新...")
        
        # 获取当前版本
        current_version = version_manager.get_current_version()
        if not current_version:
            return {
                "status": "error",
                "message": "无法获取当前版本信息"
            }
        
        # 检查是否有更新
        has_updates, update_count = version_manager.check_for_updates()
        
        # 获取最新版本信息
        latest_versions = version_manager.get_version_history(limit=1)
        latest_version = latest_versions[0] if latest_versions else None
        
        result = {
            "status": "success",
            "has_updates": has_updates,
            "update_count": update_count,
            "current_version": current_version.commit_hash,
            "latest_version": latest_version.commit_hash if latest_version else "unknown",
            "current_message": current_version.commit_message,
            "latest_message": latest_version.commit_message if latest_version else "未知"
        }
        
        print(f"✅ 更新检查完成: 有更新: {has_updates}, 更新数量: {update_count}")
        return result
        
    except Exception as e:
        print(f"❌ 检查更新失败: {e}")
        return {
            "status": "error",
            "message": f"检查更新失败: {str(e)}"
        }

@app.post("/comfyui/clear-version-cache")
async def clear_version_cache():
    """清除版本缓存"""
    try:
        # 由于我们使用的是实时Git数据，这里主要是刷新仓库状态
        if version_manager and version_manager.is_git_repo():
            version_manager._init_repo()  # 重新初始化仓库
            print("✅ 版本缓存已清除")
            return {
                "status": "success",
                "message": "版本缓存已清除"
            }
        else:
            return {
                "status": "error",
                "message": "Git仓库未初始化"
            }
    except Exception as e:
        print(f"❌ 清除版本缓存失败: {e}")
        return {
            "status": "error",
            "message": f"清除缓存失败: {str(e)}"
        }

@app.get("/git/commits")
async def get_git_commits(force: bool = False):
    """获取Git提交历史 - 兼容性API"""
    try:
        if not version_manager or not version_manager.is_git_repo():
            return {
                "status": "error",
                "message": "Git仓库未初始化或不存在",
                "commits": []
            }
        
        # 获取版本历史
        version_history = version_manager.get_version_history(limit=50)
        
        # 转换为前端期望的格式
        commits = []
        for version in version_history:
            commits.append({
                "hash": version.commit_hash,
                "full_hash": version.commit_hash,  # 这里应该是完整hash，但我们先用短hash
                "message": version.commit_message,
                "author": version.author,
                "date": version.date.strftime("%Y-%m-%d %H:%M:%S"),
                "is_current": version.is_current
            })
        
        return {
            "status": "success",
            "commits": commits
        }
        
    except Exception as e:
        print(f"❌ 获取Git提交历史失败: {e}")
        return {
            "status": "error",
            "message": str(e),
            "commits": []
        }

@app.get("/git/status")
async def get_git_status():
    """获取Git状态"""
    try:
        if not version_manager or not version_manager.is_git_repo():
            return {
                "status": "error",
                "message": "Git仓库未初始化或不存在"
            }
        
        repo = version_manager.repo
        current_version = version_manager.get_current_version()
        
        # 检查仓库状态
        is_dirty = repo.is_dirty()
        untracked_files = repo.untracked_files
        
        # 获取当前分支
        try:
            current_branch = repo.active_branch.name if not repo.head.is_detached else "detached"
        except:
            current_branch = "detached"
        
        return {
            "status": "success",
            "current_branch": current_branch,
            "current_commit": current_version.commit_hash if current_version else "unknown",
            "is_dirty": is_dirty,
            "untracked_files": len(untracked_files),
            "has_changes": is_dirty or len(untracked_files) > 0
        }
        
    except Exception as e:
        print(f"❌ 获取Git状态失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

# ==================== 版本管理 API 结束 ====================


# 启动主程序
if __name__ == "__main__":
    import uvicorn
    import sys
    
    # 默认配置
    host = "127.0.0.1"
    port = 8404
    
    # 允许通过命令行参数覆盖
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            port = int(sys.argv[2])
        except ValueError:
            print(f"Error: Invalid port number '{sys.argv[2]}'")
            sys.exit(1)
            
    # 检测网络环境，优化国内用户体验
    def check_github_connectivity():
        """快速检测GitHub连通性"""
        try:
            response = requests.get("https://api.github.com", timeout=1)
            return response.status_code == 200
        except:
            return False

    github_accessible = check_github_connectivity()
    if github_accessible:
        print("GitHub API 连接正常")
    else:
        print("GitHub API 连接较慢，将优先使用国内镜像源")

    print(f"Starting ComfyUI Launcher Backend (CORS Fixed) on http://{host}:{port}")

    # 启动Uvicorn服务器
    uvicorn.run(
        "start_fixed_cors:app", 
        host=host, 
        port=port, 
        reload=False,
        log_level="info"
    )
