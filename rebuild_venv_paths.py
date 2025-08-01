#!/usr/bin/env python3
"""
重建虚拟环境路径配置脚本
专门解决便携包移动后pip路径不正确的问题
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil

def rebuild_venv_paths():
    """重建虚拟环境路径配置"""
    try:
        # 获取当前脚本所在目录（launcher目录）
        launcher_dir = Path(__file__).parent
        portable_root = launcher_dir.parent
        venv_dir = portable_root / "venv"
        python_dir = portable_root / "python"
        
        print(f"便携包根目录: {portable_root}")
        print(f"虚拟环境目录: {venv_dir}")
        print(f"Python目录: {python_dir}")
        print()
        
        # 1. 备份重要的site-packages
        site_packages = venv_dir / "Lib" / "site-packages"
        backup_dir = portable_root / "venv_backup"
        
        if site_packages.exists():
            print("备份site-packages...")
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(site_packages, backup_dir / "site-packages")
            print("✓ site-packages备份完成")
        
        # 2. 删除虚拟环境配置文件
        config_files = [
            venv_dir / "pyvenv.cfg",
            venv_dir / "Scripts" / "activate.bat",
            venv_dir / "Scripts" / "activate",
            venv_dir / "Scripts" / "activate.ps1",
            venv_dir / "Scripts" / "deactivate.bat"
        ]
        
        print("\n删除旧的配置文件...")
        for config_file in config_files:
            if config_file.exists():
                config_file.unlink()
                print(f"✓ 删除: {config_file.name}")
        
        # 3. 重新创建虚拟环境配置
        print("\n重新创建虚拟环境配置...")
        
        # 创建新的pyvenv.cfg
        pyvenv_cfg_content = f"""home = {python_dir}
implementation = CPython
version_info = 3.12.9.final.0
virtualenv = 20.31.2
include-system-site-packages = false
base-prefix = {python_dir}
base-exec-prefix = {python_dir}
base-executable = {python_dir / 'python.exe'}
"""
        
        with open(venv_dir / "pyvenv.cfg", 'w', encoding='utf-8') as f:
            f.write(pyvenv_cfg_content)
        print("✓ 创建新的pyvenv.cfg")
        
        # 4. 重新创建激活脚本
        activate_bat_content = f"""@echo off

rem This file must be used with "call bin\\activate.bat" *from the command line*.
rem This file is UTF-8 encoded, so we need to update the current code page while executing it
for /f "tokens=2 delims=:." %%a in ('"%SystemRoot%\\System32\\chcp.com"') do (
    set _OLD_CODEPAGE=%%a
)
if defined _OLD_CODEPAGE (
    "%SystemRoot%\\System32\\chcp.com" 65001 > nul
)

set "VIRTUAL_ENV={venv_dir}"

if not defined PROMPT set "PROMPT=$P$G"

if defined _OLD_VIRTUAL_PROMPT set "PROMPT=%_OLD_VIRTUAL_PROMPT%"
if defined _OLD_VIRTUAL_PYTHONHOME set "PYTHONHOME=%_OLD_VIRTUAL_PYTHONHOME%"

set "_OLD_VIRTUAL_PROMPT=%PROMPT%"
set "PROMPT=(venv) %PROMPT%"

if defined PYTHONHOME set "_OLD_VIRTUAL_PYTHONHOME=%PYTHONHOME%"
set PYTHONHOME=

if defined _OLD_VIRTUAL_PATH set "PATH=%_OLD_VIRTUAL_PATH%"
if not defined _OLD_VIRTUAL_PATH set "_OLD_VIRTUAL_PATH=%PATH%"

set "PATH=%VIRTUAL_ENV%\\Scripts;%PATH%"

if defined _OLD_CODEPAGE (
    "%SystemRoot%\\System32\\chcp.com" %_OLD_CODEPAGE% > nul
    set "_OLD_CODEPAGE="
)

:END
if defined _OLD_CODEPAGE (
    "%SystemRoot%\\System32\\chcp.com" %_OLD_CODEPAGE% > nul
)
"""
        
        with open(venv_dir / "Scripts" / "activate.bat", 'w', encoding='utf-8') as f:
            f.write(activate_bat_content)
        print("✓ 创建新的activate.bat")
        
        # 5. 恢复site-packages
        if backup_dir.exists():
            print("\n恢复site-packages...")
            if site_packages.exists():
                shutil.rmtree(site_packages)
            shutil.copytree(backup_dir / "site-packages", site_packages)
            shutil.rmtree(backup_dir)
            print("✓ site-packages恢复完成")
        
        # 6. 重新安装pip
        print("\n重新安装pip...")
        python_exe = venv_dir / "Scripts" / "python.exe"
        result = subprocess.run([
            str(python_exe), "-m", "ensurepip", "--upgrade"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✓ pip重新安装成功")
        else:
            print(f"警告: pip重新安装失败: {result.stderr}")
        
        # 7. 验证修复结果
        print("\n验证修复结果...")
        
        # 测试Python路径
        result = subprocess.run([
            str(python_exe), "-c", "import sys; print('Python路径:', sys.executable)"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✓ Python路径: {result.stdout.strip()}")
        
        # 测试pip路径
        pip_exe = venv_dir / "Scripts" / "pip.exe"
        result = subprocess.run([
            str(pip_exe), "--version"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✓ Pip版本: {result.stdout.strip()}")
        
        print("\n✅ 虚拟环境路径重建完成！")
        return True
        
    except Exception as e:
        print(f"❌ 重建虚拟环境路径时出错: {e}")
        return False

if __name__ == "__main__":
    print("=== 虚拟环境路径重建工具 ===")
    print("此工具将重建虚拟环境配置以修复路径问题")
    print()
    
    if rebuild_venv_paths():
        print("重建成功！现在可以正常使用虚拟环境了。")
    else:
        print("重建失败！请检查错误信息。")
        sys.exit(1)
