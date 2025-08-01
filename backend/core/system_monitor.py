"""
系统监控模块
提供GPU、内存、网络等系统资源监控功能
"""
import psutil
import platform
import subprocess
import json
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class GPUInfo:
    """GPU信息"""
    id: int
    name: str
    memory_total: int  # MB
    memory_used: int   # MB
    memory_free: int   # MB
    utilization: float  # %
    temperature: float  # °C


@dataclass
class SystemStatus:
    """系统状态"""
    cpu_percent: float
    memory_percent: float
    memory_used: int  # MB
    memory_total: int  # MB
    disk_usage: float
    network_sent: int  # bytes
    network_recv: int  # bytes
    gpu_info: List[GPUInfo]
    timestamp: datetime


class SystemMonitor:
    """系统监控器"""
    
    def __init__(self):
        self.last_network_stats = None
        self.monitoring = False
        self.callbacks = []
    
    def get_gpu_info(self) -> List[GPUInfo]:
        """获取GPU信息"""
        gpu_info = []
        
        try:
            # 尝试使用nvidia-smi获取NVIDIA GPU信息
            result = subprocess.run([
                'nvidia-smi', 
                '--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu',
                '--format=csv,noheader,nounits'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip():
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 7:
                            gpu_info.append(GPUInfo(
                                id=int(parts[0]),
                                name=parts[1],
                                memory_total=int(parts[2]),
                                memory_used=int(parts[3]),
                                memory_free=int(parts[4]),
                                utilization=float(parts[5] or 0),
                                temperature=float(parts[6] or 0)
                            ))
        
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            # nvidia-smi不可用，尝试其他方法
            pass
        
        # 如果没有检测到GPU，返回空列表
        if not gpu_info:
            try:
                # 尝试检测AMD GPU或其他GPU
                import torch
                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        props = torch.cuda.get_device_properties(i)
                        gpu_info.append(GPUInfo(
                            id=i,
                            name=props.name,
                            memory_total=props.total_memory // (1024 * 1024),
                            memory_used=0,  # torch无法直接获取已使用内存
                            memory_free=props.total_memory // (1024 * 1024),
                            utilization=0.0,
                            temperature=0.0
                        ))
            except ImportError:
                pass
        
        return gpu_info
    
    def get_system_status(self) -> SystemStatus:
        """获取系统状态"""
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 内存信息
        memory = psutil.virtual_memory()
        memory_used_mb = memory.used // (1024 * 1024)
        memory_total_mb = memory.total // (1024 * 1024)
        
        # 磁盘使用率
        disk = psutil.disk_usage('/')
        disk_usage = (disk.used / disk.total) * 100
        
        # 网络信息
        network = psutil.net_io_counters()
        network_sent = network.bytes_sent
        network_recv = network.bytes_recv
        
        # GPU信息
        gpu_info = self.get_gpu_info()
        
        return SystemStatus(
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used=memory_used_mb,
            memory_total=memory_total_mb,
            disk_usage=disk_usage,
            network_sent=network_sent,
            network_recv=network_recv,
            gpu_info=gpu_info,
            timestamp=datetime.now()
        )
    
    def get_system_info(self) -> Dict[str, Any]:
        """获取系统基础信息"""
        info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "memory_total": psutil.virtual_memory().total // (1024 * 1024),  # MB
            "python_version": platform.python_version(),
        }
        
        # 检查CUDA
        try:
            import torch
            info["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                info["cuda_version"] = torch.version.cuda
                info["cuda_device_count"] = torch.cuda.device_count()
                info["cuda_device_name"] = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else None
        except ImportError:
            info["cuda_available"] = False
            info["cuda_version"] = None
        
        return info
    
    def check_port_availability(self, port: int) -> bool:
        """检查端口是否可用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', port))
                return True
            except OSError:
                return False
    
    def get_port_usage(self, start_port: int = 8180, end_port: int = 8200) -> Dict[int, bool]:
        """获取端口使用情况"""
        port_status = {}
        for port in range(start_port, end_port + 1):
            port_status[port] = self.check_port_availability(port)
        return port_status
    
    def get_comfyui_process_info(self) -> Optional[Dict[str, Any]]:
        """获取ComfyUI进程信息"""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and len(cmdline) > 0:
                    # 检查是否是ComfyUI进程
                    cmdline_str = ' '.join(cmdline)
                    if 'main.py' in cmdline_str or 'comfyui' in cmdline_str.lower():
                        # 获取详细进程信息
                        process = psutil.Process(proc.info['pid'])
                        return {
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "cmdline": cmdline,
                            "cpu_percent": process.cpu_percent(),
                            "memory_mb": proc.info['memory_info'].rss // (1024 * 1024),
                            "status": process.status(),
                            "create_time": datetime.fromtimestamp(process.create_time()),
                            "num_threads": process.num_threads()
                        }
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        return None
    
    def add_callback(self, callback):
        """添加监控回调函数"""
        self.callbacks.append(callback)
    
    def remove_callback(self, callback):
        """移除监控回调函数"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    async def start_monitoring(self, interval: float = 1.0):
        """开始监控"""
        self.monitoring = True
        while self.monitoring:
            try:
                status = self.get_system_status()
                
                # 调用所有回调函数
                for callback in self.callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(status)
                        else:
                            callback(status)
                    except Exception as e:
                        logger.error(f"监控回调函数执行失败: {e}")
                
                await asyncio.sleep(interval)
            
            except Exception as e:
                logger.error(f"系统监控出错: {e}")
                await asyncio.sleep(interval)
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
    
    def get_process_by_port(self, port: int) -> Optional[Dict[str, Any]]:
        """根据端口获取进程信息"""
        try:
            for conn in psutil.net_connections():
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    try:
                        proc = psutil.Process(conn.pid)
                        return {
                            "pid": conn.pid,
                            "name": proc.name(),
                            "cmdline": proc.cmdline(),
                            "status": proc.status()
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
        except Exception as e:
            logger.error(f"获取端口 {port} 进程信息失败: {e}")
        
        return None


# 全局系统监控实例
system_monitor = SystemMonitor()