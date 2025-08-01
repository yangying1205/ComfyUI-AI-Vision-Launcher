"""
ComfyUI Launcher 核心配置管理
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import json
import os
from pathlib import Path


class PrecisionMode(str, Enum):
    """精度模式枚举"""
    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"
    FP8_E4M3FN = "fp8_e4m3fn"
    FP8_E5M2 = "fp8_e5m2"


class MemoryOptimization(str, Enum):
    """内存优化等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ListenMode(str, Enum):
    """监听模式"""
    LOCAL = "127.0.0.1"
    LAN = "0.0.0.0"
    ALL = "0.0.0.0,::"


class LaunchConfig(BaseModel):
    """启动配置模型"""
    # 基础配置
    port: int = Field(default=8188, ge=1024, le=65535, description="端口号")
    listen: ListenMode = Field(default=ListenMode.LOCAL, description="监听地址")
    auto_launch: bool = Field(default=True, description="自动启动浏览器")
    
    # 性能配置
    cuda_device: Optional[int] = Field(default=None, description="CUDA设备ID")
    precision_mode: PrecisionMode = Field(default=PrecisionMode.FP16, description="精度模式")
    memory_optimization: MemoryOptimization = Field(default=MemoryOptimization.MEDIUM, description="内存优化等级")
    force_channels_last: bool = Field(default=False, description="强制channels last格式")
    
    # 路径配置
    base_directory: Optional[str] = Field(default=None, description="基础目录")
    output_directory: Optional[str] = Field(default=None, description="输出目录")
    input_directory: Optional[str] = Field(default=None, description="输入目录")
    temp_directory: Optional[str] = Field(default=None, description="临时目录")
    extra_model_paths: List[str] = Field(default=[], description="额外模型路径")
    
    # 高级配置
    log_level: str = Field(default="INFO", description="日志级别")
    enable_cors: bool = Field(default=False, description="启用CORS")
    cors_origin: str = Field(default="*", description="CORS来源")
    max_upload_size: float = Field(default=100.0, description="最大上传大小(MB)")
    
    # 实验性功能
    enable_torch_compile: bool = Field(default=False, description="启用Torch编译")
    preview_method: str = Field(default="auto", description="预览方法")


class SystemInfo(BaseModel):
    """系统信息模型"""
    gpu_count: int
    gpu_names: List[str]
    total_memory: int
    available_memory: int
    cpu_count: int
    platform: str
    python_version: str
    cuda_available: bool
    cuda_version: Optional[str]


class VersionInfo(BaseModel):
    """版本信息模型"""
    current_commit: str
    current_branch: str
    current_tag: Optional[str]
    available_tags: List[str]
    available_branches: List[str]
    is_dirty: bool
    remote_url: Optional[str]


class LauncherSettings(BaseModel):
    """启动器设置"""
    theme: str = Field(default="cyberpunk", description="主题")
    language: str = Field(default="zh", description="语言")
    auto_check_updates: bool = Field(default=True, description="自动检查更新")
    minimize_to_tray: bool = Field(default=True, description="最小化到托盘")
    start_with_system: bool = Field(default=False, description="开机启动")
    enable_sounds: bool = Field(default=True, description="启用音效")
    opacity: float = Field(default=0.95, ge=0.5, le=1.0, description="界面透明度")
    window_width: int = Field(default=1200, description="窗口宽度")
    window_height: int = Field(default=800, description="窗口高度")


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.launch_config_file = self.config_dir / "launch_config.json"
        self.launcher_settings_file = self.config_dir / "launcher_settings.json"
        self.presets_dir = self.config_dir / "presets"
        self.presets_dir.mkdir(exist_ok=True)
    
    def load_launch_config(self) -> LaunchConfig:
        """加载启动配置"""
        if self.launch_config_file.exists():
            try:
                with open(self.launch_config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return LaunchConfig(**data)
            except Exception as e:
                print(f"加载启动配置失败: {e}")
        
        return LaunchConfig()
    
    def save_launch_config(self, config: LaunchConfig) -> bool:
        """保存启动配置"""
        try:
            with open(self.launch_config_file, 'w', encoding='utf-8') as f:
                json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存启动配置失败: {e}")
            return False
    
    def load_launcher_settings(self) -> LauncherSettings:
        """加载启动器设置"""
        if self.launcher_settings_file.exists():
            try:
                with open(self.launcher_settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return LauncherSettings(**data)
            except Exception as e:
                print(f"加载启动器设置失败: {e}")
        
        return LauncherSettings()
    
    def save_launcher_settings(self, settings: LauncherSettings) -> bool:
        """保存启动器设置"""
        try:
            with open(self.launcher_settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings.model_dump(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存启动器设置失败: {e}")
            return False
    
    def get_presets(self) -> Dict[str, LaunchConfig]:
        """获取所有预设"""
        presets = {}
        for preset_file in self.presets_dir.glob("*.json"):
            try:
                with open(preset_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                presets[preset_file.stem] = LaunchConfig(**data)
            except Exception as e:
                print(f"加载预设 {preset_file.name} 失败: {e}")
        
        return presets
    
    def save_preset(self, name: str, config: LaunchConfig) -> bool:
        """保存预设"""
        try:
            preset_file = self.presets_dir / f"{name}.json"
            with open(preset_file, 'w', encoding='utf-8') as f:
                json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存预设 {name} 失败: {e}")
            return False
    
    def delete_preset(self, name: str) -> bool:
        """删除预设"""
        try:
            preset_file = self.presets_dir / f"{name}.json"
            if preset_file.exists():
                preset_file.unlink()
            return True
        except Exception as e:
            print(f"删除预设 {name} 失败: {e}")
            return False


# 默认预设配置
DEFAULT_PRESETS = {
    "high_performance": LaunchConfig(
        precision_mode=PrecisionMode.FP16,
        memory_optimization=MemoryOptimization.LOW,
        force_channels_last=True,
        enable_torch_compile=True,
        preview_method="latent2rgb"
    ),
    "quality_first": LaunchConfig(
        precision_mode=PrecisionMode.FP32,
        memory_optimization=MemoryOptimization.HIGH,
        force_channels_last=False,
        enable_torch_compile=False,
        preview_method="taesd"
    ),
    "speed_first": LaunchConfig(
        precision_mode=PrecisionMode.FP8_E4M3FN,
        memory_optimization=MemoryOptimization.LOW,
        force_channels_last=True,
        enable_torch_compile=True,
        preview_method="none"
    )
}


def create_default_presets(config_manager: ConfigManager):
    """创建默认预设"""
    for name, config in DEFAULT_PRESETS.items():
        config_manager.save_preset(name, config)