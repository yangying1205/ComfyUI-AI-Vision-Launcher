#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复虚拟环境路径配置，使其支持便携性
"""
import os
import sys
from pathlib import Path

def check_venv_paths_need_fix():
    """检查虚拟环境路径是否需要修复"""
    try:
        launcher_dir = Path(__file__).parent
        portable_root = launcher_dir.parent
        venv_dir = portable_root / "venv"

        # 检查 pyvenv.cfg 文件
        pyvenv_cfg = venv_dir / "pyvenv.cfg"
        if not pyvenv_cfg.exists():
            return True, "pyvenv.cfg文件不存在"

        # 读取当前配置
        with open(pyvenv_cfg, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查路径是否正确
        current_portable_root = str(portable_root).replace('\\', '\\\\')

        if current_portable_root not in content:
            return True, f"路径不匹配，需要从旧路径更新到: {portable_root}"

        # 检查 activate.bat
        activate_bat = venv_dir / "Scripts" / "activate.bat"
        if activate_bat.exists():
            with open(activate_bat, 'r', encoding='utf-8') as f:
                bat_content = f.read()

            expected_venv_path = str(venv_dir)
            if f'VIRTUAL_ENV={expected_venv_path}' not in bat_content:
                return True, f"activate.bat中的VIRTUAL_ENV路径需要更新"

        return False, "虚拟环境路径配置正确"

    except Exception as e:
        return True, f"检查虚拟环境路径时出错: {e}"

def fix_venv_portable_paths():
    """修复虚拟环境配置文件中的绝对路径为相对路径"""
    try:
        # 获取当前脚本所在目录（launcher目录）
        launcher_dir = Path(__file__).parent
        portable_root = launcher_dir.parent
        venv_dir = portable_root / "venv"
        python_dir = portable_root / "python"

        print(f"便携包根目录: {portable_root}")
        print(f"虚拟环境目录: {venv_dir}")
        print(f"Python目录: {python_dir}")

        # 首先检查是否需要修复
        needs_fix, reason = check_venv_paths_need_fix()
        if not needs_fix:
            print(f"✓ {reason}")
            return True

        print(f"需要修复: {reason}")
        success = True

        # 1. 修复 pyvenv.cfg 文件
        pyvenv_cfg = venv_dir / "pyvenv.cfg"

        if not pyvenv_cfg.exists():
            print(f"警告: 虚拟环境配置文件不存在: {pyvenv_cfg}")
            success = False
        else:
            # 读取当前配置
            with open(pyvenv_cfg, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 修复路径配置
            fixed_lines = []
            python_path = str(python_dir).replace('\\', '\\\\')  # Windows路径需要转义

            for line in lines:
                line = line.strip()
                if line.startswith('home ='):
                    fixed_lines.append(f'home = {python_path}\n')
                    print(f"修复 home 路径: {python_path}")
                elif line.startswith('base-prefix ='):
                    fixed_lines.append(f'base-prefix = {python_path}\n')
                    print(f"修复 base-prefix 路径: {python_path}")
                elif line.startswith('base-exec-prefix ='):
                    fixed_lines.append(f'base-exec-prefix = {python_path}\n')
                    print(f"修复 base-exec-prefix 路径: {python_path}")
                elif line.startswith('base-executable ='):
                    fixed_lines.append(f'base-executable = {python_path}\\python.exe\n')
                    print(f"修复 base-executable 路径: {python_path}\\python.exe")
                else:
                    fixed_lines.append(line + '\n' if line else '\n')

            # 写入修复后的配置
            with open(pyvenv_cfg, 'w', encoding='utf-8') as f:
                f.writelines(fixed_lines)

            print(f"✓ pyvenv.cfg 路径配置已修复: {pyvenv_cfg}")

        # 2. 修复 activate.bat 脚本
        activate_bat = venv_dir / "Scripts" / "activate.bat"

        if not activate_bat.exists():
            print(f"警告: 激活脚本不存在: {activate_bat}")
            success = False
        else:
            # 读取当前激活脚本
            with open(activate_bat, 'r', encoding='utf-8') as f:
                content = f.read()

            # 修复 VIRTUAL_ENV 路径（第8行）
            venv_path = str(venv_dir)

            # 使用正则表达式替换硬编码的路径
            import re
            pattern = r'@set "VIRTUAL_ENV=.*?"'
            # 转义反斜杠以避免正则表达式错误
            escaped_venv_path = venv_path.replace('\\', '\\\\')
            replacement = f'@set "VIRTUAL_ENV={escaped_venv_path}"'

            new_content = re.sub(pattern, replacement, content)

            # 写入修复后的激活脚本
            with open(activate_bat, 'w', encoding='utf-8') as f:
                f.write(new_content)

            print(f"✓ activate.bat 路径配置已修复: {activate_bat}")
            print(f"  VIRTUAL_ENV 设置为: {venv_path}")

        # 3. 修复其他激活脚本（如果存在）
        scripts_to_fix = [
            ("activate", "VIRTUAL_ENV="),
            ("Activate.ps1", "$VenvDir = "),
        ]

        for script_name, pattern_start in scripts_to_fix:
            script_path = venv_dir / "Scripts" / script_name
            if script_path.exists():
                try:
                    with open(script_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # 简单的路径替换（针对不同脚本格式）
                    if script_name == "activate":
                        # Unix风格的activate脚本
                        pattern = r'VIRTUAL_ENV=".*"'
                        replacement = f'VIRTUAL_ENV="{venv_path}"'
                        new_content = re.sub(pattern, replacement, content)
                    elif script_name == "Activate.ps1":
                        # PowerShell脚本需要特殊处理
                        # 这里暂时跳过，因为结构比较复杂
                        continue

                    with open(script_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

                    print(f"✓ {script_name} 路径配置已修复")

                except Exception as e:
                    print(f"警告: 修复 {script_name} 时出错: {e}")

        # 4. 强制重新安装pip以修复路径问题
        print("\n正在重新安装pip以修复路径...")
        try:
            import subprocess

            # 使用当前虚拟环境的Python重新安装pip
            python_exe = venv_dir / "Scripts" / "python.exe"
            result = subprocess.run([
                str(python_exe), "-m", "pip", "install", "--force-reinstall", "--no-deps", "pip"
            ], capture_output=True, text=True, cwd=str(portable_root))

            if result.returncode == 0:
                print("✓ pip重新安装成功，路径问题已修复")
            else:
                print(f"警告: pip重新安装失败: {result.stderr}")

        except Exception as pip_error:
            print(f"警告: 重新安装pip时出错: {pip_error}")

        return success

    except Exception as e:
        print(f"✗ 修复虚拟环境路径配置失败: {e}")
        return False

def check_venv_activation():
    """检查虚拟环境是否正确激活"""
    try:
        # 检查是否在虚拟环境中
        venv_active = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        
        if venv_active:
            print(f"✓ 虚拟环境已激活: {sys.prefix}")
        else:
            print(f"✗ 虚拟环境未激活，当前Python路径: {sys.executable}")
            
        return venv_active
        
    except Exception as e:
        print(f"✗ 检查虚拟环境状态失败: {e}")
        return False

if __name__ == "__main__":
    print("=== Portable Virtual Environment Path Fix Tool ===")

    # 修复虚拟环境路径配置
    if fix_venv_portable_paths():
        print("Virtual environment path configuration fixed successfully")
    else:
        print("Failed to fix virtual environment path configuration")
        sys.exit(1)

    # 检查虚拟环境状态
    check_venv_activation()
