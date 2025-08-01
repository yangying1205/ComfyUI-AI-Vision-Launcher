"""
进程管理模块
负责ComfyUI进程的启动、停止、监控等操作
"""
import subprocess
import psutil
import os
import signal
import asyncio
import logging
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

from .config import LaunchConfig

logger = logging.getLogger(__name__)


class ProcessStatus(Enum):
    """进程状态枚举"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ProcessInfo:
    """进程信息"""
    pid: Optional[int]
    status: ProcessStatus
    start_time: Optional[datetime]
    cpu_percent: float
    memory_mb: int
    command: List[str]
    working_dir: str
    port: int


class ProcessManager:
    """进程管理器"""
    
    def __init__(self, project_path: str = None):
        if project_path is None:
            # 默认指向ComfyUI项目根目录
            project_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        
        self.project_path = Path(project_path)
        self.process: Optional[subprocess.Popen] = None
        self.status = ProcessStatus.STOPPED
        self.start_time: Optional[datetime] = None
        self.callbacks: List[Callable] = []
        self.monitoring_task: Optional[asyncio.Task] = None
        self.current_config: Optional[LaunchConfig] = None
    
    def add_status_callback(self, callback: Callable[[ProcessStatus, ProcessInfo], None]):
        """添加状态变化回调"""
        self.callbacks.append(callback)
    
    def remove_status_callback(self, callback: Callable):
        """移除状态变化回调"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def _notify_status_change(self, old_status: ProcessStatus, new_status: ProcessStatus):
        """通知状态变化"""
        self.status = new_status
        process_info = self.get_process_info()
        
        for callback in self.callbacks:
            try:
                callback(new_status, process_info)
            except Exception as e:
                logger.error(f"状态回调执行失败: {e}")
    
    def _build_command(self, config: LaunchConfig) -> List[str]:
        """构建启动命令"""
        # 基础命令
        cmd = ["python", "main.py"]
        
        # 基础配置
        cmd.extend(["--port", str(config.port)])
        cmd.extend(["--listen", config.listen.value])
        
        if config.auto_launch:
            cmd.append("--auto-launch")
        else:
            cmd.append("--disable-auto-launch")
        
        # 性能配置
        if config.cuda_device is not None:
            cmd.extend(["--cuda-device", str(config.cuda_device)])
        
        # 精度配置
        if config.precision_mode.value != "fp16":  # fp16是默认值
            if config.precision_mode.value == "fp32":
                cmd.append("--force-fp32")
            elif config.precision_mode.value == "bf16":
                cmd.append("--bf16-unet")
            elif config.precision_mode.value == "fp8_e4m3fn":
                cmd.append("--fp8_e4m3fn-unet")
            elif config.precision_mode.value == "fp8_e5m2":
                cmd.append("--fp8_e5m2-unet")
        
        # 内存优化
        if config.memory_optimization.value == "high":
            cmd.append("--lowvram")
        elif config.memory_optimization.value == "low":
            cmd.append("--normalvram")
        
        if config.force_channels_last:
            cmd.append("--force-channels-last")
        
        # 路径配置
        if config.base_directory:
            cmd.extend(["--base-directory", config.base_directory])
        
        if config.output_directory:
            cmd.extend(["--output-directory", config.output_directory])
        
        if config.input_directory:
            cmd.extend(["--input-directory", config.input_directory])
        
        if config.temp_directory:
            cmd.extend(["--temp-directory", config.temp_directory])
        
        for extra_path in config.extra_model_paths:
            cmd.extend(["--extra-model-paths-config", extra_path])
        
        # 高级配置
        if config.enable_cors:
            cmd.extend(["--enable-cors-header", config.cors_origin])
        
        cmd.extend(["--max-upload-size", str(config.max_upload_size)])
        
        # 实验性功能
        if config.enable_torch_compile:
            # 这里需要根据ComfyUI的实际参数来调整
            pass
        
        cmd.extend(["--preview-method", config.preview_method])
        
        return cmd
    
    def _setup_environment(self) -> Dict[str, str]:
        """设置环境变量"""
        env = os.environ.copy()
        
        # 禁用遥测
        env['HF_HUB_DISABLE_TELEMETRY'] = '1'
        env['DO_NOT_TRACK'] = '1'
        
        return env
    
    async def start(self, config: LaunchConfig) -> bool:
        """启动ComfyUI进程"""
        if self.status in [ProcessStatus.STARTING, ProcessStatus.RUNNING]:
            logger.warning("进程已在运行或正在启动")
            return False
        
        try:
            old_status = self.status
            self._notify_status_change(old_status, ProcessStatus.STARTING)
            
            # 构建命令
            cmd = self._build_command(config)
            env = self._setup_environment()
            
            logger.info(f"启动命令: {' '.join(cmd)}")
            logger.info(f"工作目录: {self.project_path}")
            
            # 激活conda环境并启动进程
            if os.name == 'nt':  # Windows
                # Windows下需要通过cmd来激活conda环境
                conda_cmd = f"conda activate ./venv && {' '.join(cmd)}"
                self.process = subprocess.Popen(
                    conda_cmd,
                    shell=True,
                    cwd=self.project_path,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
            else:
                # Linux/Mac
                conda_cmd = ["conda", "run", "-p", "./venv"] + cmd
                self.process = subprocess.Popen(
                    conda_cmd,
                    cwd=self.project_path,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
            
            self.current_config = config
            self.start_time = datetime.now()
            
            # 等待进程启动
            await asyncio.sleep(2)
            
            # 检查进程是否正常启动
            if self.process.poll() is None:
                self._notify_status_change(ProcessStatus.STARTING, ProcessStatus.RUNNING)
                
                # 启动监控任务
                self.monitoring_task = asyncio.create_task(self._monitor_process())
                
                return True
            else:
                # 进程启动失败
                stdout, stderr = self.process.communicate()
                logger.error(f"进程启动失败: {stderr}")
                self._notify_status_change(ProcessStatus.STARTING, ProcessStatus.ERROR)
                return False
        
        except Exception as e:
            logger.error(f"启动进程失败: {e}")
            self._notify_status_change(ProcessStatus.STARTING, ProcessStatus.ERROR)
            return False
    
    async def stop(self, force: bool = False) -> bool:
        """停止ComfyUI进程"""
        if self.status in [ProcessStatus.STOPPED, ProcessStatus.STOPPING]:
            return True
        
        try:
            old_status = self.status
            self._notify_status_change(old_status, ProcessStatus.STOPPING)
            
            if self.process:
                if force:
                    # 强制终止
                    self.process.kill()
                else:
                    # 优雅关闭
                    self.process.terminate()
                
                # 等待进程结束
                try:
                    await asyncio.wait_for(
                        asyncio.create_task(self._wait_for_process()),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("进程未在预期时间内结束，强制终止")
                    self.process.kill()
                    await self._wait_for_process()
            
            # 停止监控任务
            if self.monitoring_task:
                self.monitoring_task.cancel()
                self.monitoring_task = None
            
            self.process = None
            self.start_time = None
            self.current_config = None
            
            self._notify_status_change(ProcessStatus.STOPPING, ProcessStatus.STOPPED)
            return True
        
        except Exception as e:
            logger.error(f"停止进程失败: {e}")
            self._notify_status_change(ProcessStatus.STOPPING, ProcessStatus.ERROR)
            return False
    
    async def restart(self, config: Optional[LaunchConfig] = None) -> bool:
        """重启ComfyUI进程"""
        if config is None:
            config = self.current_config
        
        if config is None:
            logger.error("无法重启：缺少配置信息")
            return False
        
        # 停止当前进程
        await self.stop()
        
        # 等待一秒
        await asyncio.sleep(1)
        
        # 启动新进程
        return await self.start(config)
    
    async def _wait_for_process(self):
        """等待进程结束"""
        if self.process:
            while self.process.poll() is None:
                await asyncio.sleep(0.1)
    
    async def _monitor_process(self):
        """监控进程状态"""
        try:
            while self.process and self.process.poll() is None:
                await asyncio.sleep(1)
            
            # 进程意外结束
            if self.status == ProcessStatus.RUNNING:
                logger.warning("ComfyUI进程意外结束")
                self._notify_status_change(ProcessStatus.RUNNING, ProcessStatus.ERROR)
        
        except asyncio.CancelledError:
            # 监控任务被取消
            pass
        except Exception as e:
            logger.error(f"进程监控出错: {e}")
    
    def get_process_info(self) -> ProcessInfo:
        """获取进程信息"""
        pid = None
        cpu_percent = 0.0
        memory_mb = 0
        
        if self.process and self.status == ProcessStatus.RUNNING:
            try:
                pid = self.process.pid
                proc = psutil.Process(pid)
                cpu_percent = proc.cpu_percent()
                memory_mb = proc.memory_info().rss // (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        return ProcessInfo(
            pid=pid,
            status=self.status,
            start_time=self.start_time,
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
            command=self._build_command(self.current_config) if self.current_config else [],
            working_dir=str(self.project_path),
            port=self.current_config.port if self.current_config else 8188
        )
    
    def is_running(self) -> bool:
        """检查进程是否正在运行"""
        return self.status == ProcessStatus.RUNNING
    
    def get_logs(self, lines: int = 100) -> Dict[str, List[str]]:
        """获取进程日志"""
        logs = {"stdout": [], "stderr": []}
        
        if self.process:
            try:
                # 这里需要实现日志读取逻辑
                # 由于我们使用了PIPE，可以从process.stdout和process.stderr读取
                pass
            except Exception as e:
                logger.error(f"读取日志失败: {e}")
        
        return logs
    
    async def send_signal(self, sig: signal.Signals) -> bool:
        """向进程发送信号"""
        if not self.process or self.status != ProcessStatus.RUNNING:
            return False
        
        try:
            os.kill(self.process.pid, sig)
            return True
        except Exception as e:
            logger.error(f"发送信号失败: {e}")
            return False


# 全局进程管理实例
process_manager = ProcessManager()