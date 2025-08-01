#!/usr/bin/env python3
"""
强力修复pip路径问题
彻底清除旧路径引用并重新安装pip
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def force_fix_pip():
    """强力修复pip路径问题"""
    try:
        # 获取当前脚本所在目录
        launcher_dir = Path(__file__).parent
        portable_root = launcher_dir.parent
        venv_dir = portable_root / "venv"
        python_exe = venv_dir / "Scripts" / "python.exe"
        
        print(f"便携包位置: {portable_root}")
        print(f"虚拟环境位置: {venv_dir}")
        
        if not python_exe.exists():
            print("❌ Python可执行文件不存在")
            return False
        
        # 1. 检查当前pip状态
        print("\n=== 检查当前pip状态 ===")
        try:
            result = subprocess.run([
                str(python_exe), "-m", "pip", "--version"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"当前pip: {result.stdout.strip()}")
                
                # 检查路径是否正确
                current_path = str(portable_root).replace('\\', '/').lower()
                if current_path in result.stdout.lower():
                    print("✅ pip路径已经正确")
                    return True
                else:
                    print("⚠️ pip路径不正确，需要修复")
            else:
                print("⚠️ pip命令执行失败")
                
        except Exception as e:
            print(f"⚠️ pip检查失败: {e}")
        
        # 2. 强力清除pip相关文件
        print("\n=== 强力清除pip缓存和配置 ===")
        
        # 清除pip缓存目录
        try:
            result = subprocess.run([
                str(python_exe), "-m", "pip", "cache", "purge"
            ], capture_output=True, text=True, timeout=30)
            print("✓ pip缓存已清除")
        except:
            print("⚠️ pip缓存清除失败")
        
        # 删除pip相关的.pth文件
        site_packages = venv_dir / "Lib" / "site-packages"
        if site_packages.exists():
            for pth_file in site_packages.glob("*.pth"):
                try:
                    pth_content = pth_file.read_text(encoding='utf-8')
                    if 'pip' in pth_content.lower() or str(portable_root).replace('\\', '/') not in pth_content:
                        pth_file.unlink()
                        print(f"✓ 删除问题.pth文件: {pth_file.name}")
                except:
                    pass
        
        # 3. 卸载并重新安装pip
        print("\n=== 重新安装pip ===")
        
        try:
            # 方法1: 使用ensurepip重新安装
            print("步骤1: 使用ensurepip重新安装...")
            result1 = subprocess.run([
                str(python_exe), "-m", "ensurepip", "--upgrade", "--default-pip"
            ], capture_output=True, text=True, timeout=60)
            
            if result1.returncode == 0:
                print("✓ ensurepip安装成功")
            else:
                print(f"⚠️ ensurepip安装失败: {result1.stderr}")
            
            # 方法2: 强制重新安装pip
            print("步骤2: 强制重新安装pip...")
            result2 = subprocess.run([
                str(python_exe), "-m", "pip", "install", "--force-reinstall", "--no-deps", "--no-cache-dir", "pip"
            ], capture_output=True, text=True, timeout=60)
            
            if result2.returncode == 0:
                print("✓ pip强制重新安装成功")
            else:
                print(f"⚠️ pip强制重新安装失败: {result2.stderr}")
            
            # 方法3: 升级pip到最新版本
            print("步骤3: 升级pip到最新版本...")
            result3 = subprocess.run([
                str(python_exe), "-m", "pip", "install", "--upgrade", "--no-cache-dir", "pip"
            ], capture_output=True, text=True, timeout=60)
            
            if result3.returncode == 0:
                print("✓ pip升级成功")
            else:
                print(f"⚠️ pip升级失败: {result3.stderr}")
                
        except Exception as e:
            print(f"❌ pip重新安装过程出错: {e}")
            return False
        
        # 4. 验证修复结果
        print("\n=== 验证修复结果 ===")
        
        try:
            result = subprocess.run([
                str(python_exe), "-m", "pip", "--version"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                pip_info = result.stdout.strip()
                print(f"修复后pip: {pip_info}")
                
                # 检查路径是否正确
                current_path = str(portable_root).replace('\\', '/').lower()
                if current_path in pip_info.lower():
                    print("🎉 pip路径修复成功！")
                    return True
                else:
                    print("❌ pip路径仍然不正确")
                    print(f"期望路径包含: {current_path}")
                    print(f"实际pip信息: {pip_info}")
                    return False
            else:
                print("❌ pip验证失败")
                return False
                
        except Exception as e:
            print(f"❌ pip验证过程出错: {e}")
            return False
        
    except Exception as e:
        print(f"❌ 强力修复过程出错: {e}")
        return False

if __name__ == "__main__":
    print("=== 强力pip路径修复工具 ===")
    
    if force_fix_pip():
        print("\n🎉 修复完成！pip现在指向正确的路径。")
        sys.exit(0)
    else:
        print("\n❌ 修复失败！请尝试运行 rebuild_venv.bat 进行完整重建。")
        sys.exit(1)
