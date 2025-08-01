"""
便携包启动器性能优化器
专门针对便携包环境的性能优化
"""
import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PortablePerformanceOptimizer:
    def __init__(self, custom_nodes_dir: str):
        self.custom_nodes_dir = custom_nodes_dir
        self.cache_dir = os.path.join(os.path.dirname(__file__), 'cache')
        self.db_path = os.path.join(self.cache_dir, 'portable_cache.db')
        self.executor = ThreadPoolExecutor(max_workers=2)  # 便携包使用较少线程
        
        # 确保缓存目录存在
        os.makedirs(self.cache_dir, exist_ok=True)
        self.init_database()
        
    def init_database(self):
        """初始化SQLite缓存数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 插件缓存表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS plugin_cache (
                key TEXT PRIMARY KEY,
                data TEXT,
                timestamp REAL,
                expires_at REAL
            )
        ''')
        
        # 版本缓存表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS version_cache (
                plugin_name TEXT PRIMARY KEY,
                versions TEXT,
                current_commit TEXT,
                timestamp REAL,
                expires_at REAL
            )
        ''')
        
        conn.commit()
        conn.close()
        
    async def get_cached_plugins(self, cache_key: str = 'installed_plugins', 
                                cache_duration: int = 300) -> Optional[List[Dict]]:
        """获取缓存的插件数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        current_time = time.time()
        cursor.execute(
            "SELECT data FROM plugin_cache WHERE key = ? AND expires_at > ?",
            (cache_key, current_time)
        )
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logger.info(f"使用缓存的插件数据: {cache_key}")
            return json.loads(result[0])
        return None
        
    async def cache_plugins(self, plugins: List[Dict], cache_key: str = 'installed_plugins',
                           cache_duration: int = 300):
        """缓存插件数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        current_time = time.time()
        expires_at = current_time + cache_duration
        
        cursor.execute('''
            INSERT OR REPLACE INTO plugin_cache 
            (key, data, timestamp, expires_at) 
            VALUES (?, ?, ?, ?)
        ''', (cache_key, json.dumps(plugins), current_time, expires_at))
        
        conn.commit()
        conn.close()
        logger.info(f"插件数据已缓存: {cache_key}, 过期时间: {cache_duration}秒")
        
    async def scan_plugins_fast(self) -> List[Dict]:
        """快速扫描插件 - 便携包优化版本"""
        plugins = []
        
        if not os.path.exists(self.custom_nodes_dir):
            logger.warning(f"插件目录不存在: {self.custom_nodes_dir}")
            return plugins
            
        try:
            items = os.listdir(self.custom_nodes_dir)
            logger.info(f"开始扫描 {len(items)} 个项目")
            
            # 并发处理插件目录（便携包使用较少并发）
            tasks = []
            for item_name in items:
                if not item_name.startswith('.') and item_name != '__pycache__':
                    item_path = os.path.join(self.custom_nodes_dir, item_name)
                    if os.path.isdir(item_path):
                        task = self.process_plugin_fast(item_name, item_path)
                        tasks.append(task)
            
            # 限制并发数量
            results = []
            for i in range(0, len(tasks), 5):  # 每批处理5个
                batch = tasks[i:i+5]
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                results.extend(batch_results)
            
            for result in results:
                if isinstance(result, dict):
                    plugins.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"插件处理错误: {result}")
                    
        except Exception as e:
            logger.error(f"扫描插件目录失败: {e}")
            
        logger.info(f"扫描完成，找到 {len(plugins)} 个有效插件")
        return plugins
        
    async def process_plugin_fast(self, name: str, path: str) -> Optional[Dict]:
        """快速处理单个插件"""
        try:
            # 基本信息
            is_disabled = name.endswith('.disabled')
            actual_name = name.replace('.disabled', '') if is_disabled else name
            
            # 检查是否有Python文件（快速检查）
            has_py_files = False
            try:
                for file in os.listdir(path)[:10]:  # 只检查前10个文件
                    if file.endswith('.py'):
                        has_py_files = True
                        break
            except:
                pass
                
            if not has_py_files:
                return None
            
            # 构建插件信息
            plugin_info = {
                'name': actual_name,
                'path': path,
                'enabled': not is_disabled,
                'status': 'disabled' if is_disabled else 'enabled',
                'is_git': os.path.exists(os.path.join(path, '.git')),
                'description': f'Custom node: {actual_name}',
                'author': 'Unknown',
                'version': 'unknown',
                'date': 'unknown',
                'size': 0,  # 跳过大小计算以提高速度
                'category': 'custom',
                'hasUpdate': False
            }
            
            # 尝试快速获取更多信息
            await self.enrich_plugin_info_fast(plugin_info, path)
            
            return plugin_info
            
        except Exception as e:
            logger.error(f"处理插件 {name} 失败: {e}")
            return None
            
    async def enrich_plugin_info_fast(self, plugin_info: Dict, path: str):
        """快速丰富插件信息"""
        try:
            # 检查README文件（只读前几行）
            readme_files = ['README.md', 'readme.md']
            for readme_file in readme_files:
                readme_path = os.path.join(path, readme_file)
                if os.path.exists(readme_path):
                    try:
                        with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                            # 只读前500字符
                            content = f.read(500)
                            lines = content.split('\n')[:5]  # 只处理前5行
                            
                            for line in lines:
                                line = line.strip()
                                if line.startswith('#'):
                                    plugin_info['description'] = line.lstrip('#').strip()[:100]
                                    break
                        break
                    except:
                        pass
                        
            # 快速获取文件修改时间
            try:
                mtime = os.path.getmtime(path)
                plugin_info['date'] = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
            except:
                pass
                
        except Exception as e:
            logger.debug(f"丰富插件信息失败: {e}")
            
    async def get_cached_versions(self, plugin_name: str, cache_duration: int = 1800) -> Optional[Dict]:
        """获取缓存的版本信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        current_time = time.time()
        cursor.execute('''
            SELECT versions, current_commit FROM version_cache 
            WHERE plugin_name = ? AND expires_at > ?
        ''', (plugin_name, current_time))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logger.info(f"使用缓存的版本数据: {plugin_name}")
            return {
                "versions": json.loads(result[0]),
                "current_commit": result[1]
            }
        return None
        
    async def cache_versions(self, plugin_name: str, versions: List[Dict], current_commit: str,
                           cache_duration: int = 1800):
        """缓存版本信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        current_time = time.time()
        expires_at = current_time + cache_duration
        
        cursor.execute('''
            INSERT OR REPLACE INTO version_cache 
            (plugin_name, versions, current_commit, timestamp, expires_at) 
            VALUES (?, ?, ?, ?, ?)
        ''', (plugin_name, json.dumps(versions), current_commit, current_time, expires_at))
        
        conn.commit()
        conn.close()
        logger.info(f"版本信息已缓存: {plugin_name}")
        
    def generate_mock_versions(self, plugin_name: str) -> List[Dict]:
        """生成模拟版本数据（便携包快速响应）"""
        return [
            {
                "commit": "latest",
                "message": "最新版本",
                "author": "开发者",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "is_current": True,
                "tag": None
            },
            {
                "commit": "stable",
                "message": "稳定版本",
                "author": "开发者",
                "date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "is_current": False,
                "tag": "stable"
            }
        ]
        
    def clear_cache(self):
        """清除所有缓存"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM plugin_cache")
            cursor.execute("DELETE FROM version_cache")
            
            conn.commit()
            conn.close()
            logger.info("缓存已清除")
        except Exception as e:
            logger.error(f"清除缓存失败: {e}")
            
    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM plugin_cache")
            plugin_cache_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM version_cache")
            version_cache_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "plugin_cache_count": plugin_cache_count,
                "version_cache_count": version_cache_count,
                "cache_dir": self.cache_dir,
                "db_path": self.db_path
            }
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}")
            return {}

# 全局实例
_portable_optimizer = None

def get_portable_optimizer(custom_nodes_dir: str) -> PortablePerformanceOptimizer:
    """获取便携包性能优化器实例"""
    global _portable_optimizer
    if _portable_optimizer is None:
        _portable_optimizer = PortablePerformanceOptimizer(custom_nodes_dir)
    return _portable_optimizer
