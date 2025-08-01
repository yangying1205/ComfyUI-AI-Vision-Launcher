"""
版本管理模块
提供Git版本控制功能，支持版本切换、更新检测等
"""
import git
import os
import shutil
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """版本信息"""
    commit_hash: str
    commit_message: str
    author: str
    date: datetime
    tag: Optional[str] = None
    is_current: bool = False


@dataclass
class BranchInfo:
    """分支信息"""
    name: str
    commit_hash: str
    is_current: bool = False
    is_remote: bool = False


@dataclass  
class TagInfo:
    """标签信息"""
    name: str
    commit_hash: str
    message: str
    author: str
    date: datetime
    is_current: bool = False


class VersionManager:
    """版本管理器"""
    
    def __init__(self, project_path: str = None):
        if project_path is None:
            # 默认指向ComfyUI项目根目录
            # 当前文件: launcher/backend/core/version_manager.py
            # ComfyUI目录: launcher/../ComfyUI
            launcher_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # launcher目录
            project_path = os.path.join(os.path.dirname(launcher_dir), "ComfyUI")  # ComfyUI目录
        
        self.project_path = Path(project_path)
        self.repo = None
        self._init_repo()
    
    def _init_repo(self):
        """初始化Git仓库"""
        try:
            self.repo = git.Repo(self.project_path)
            if self.repo.bare:
                raise git.InvalidGitRepositoryError("仓库是bare仓库")
        except git.InvalidGitRepositoryError:
            logger.error(f"无效的Git仓库: {self.project_path}")
            self.repo = None
        except Exception as e:
            logger.error(f"初始化Git仓库失败: {e}")
            self.repo = None
    
    def is_git_repo(self) -> bool:
        """检查是否为Git仓库"""
        return self.repo is not None
    
    def get_current_version(self) -> Optional[VersionInfo]:
        """获取当前版本信息"""
        if not self.repo:
            return None
        
        try:
            commit = self.repo.head.commit
            
            # 检查当前提交是否有标签
            tag = None
            for t in self.repo.tags:
                if t.commit == commit:
                    tag = t.name
                    break
            
            return VersionInfo(
                commit_hash=commit.hexsha[:8],
                commit_message=commit.message.strip(),
                author=commit.author.name,
                date=datetime.fromtimestamp(commit.committed_date),
                tag=tag,
                is_current=True
            )
        except Exception as e:
            logger.error(f"获取当前版本信息失败: {e}")
            return None
    
    def get_version_history(self, limit: int = 50, use_remote: bool = False) -> List[VersionInfo]:
        """获取版本历史"""
        if not self.repo:
            return []
        
        try:
            versions = []
            current_commit = self.repo.head.commit
            
            # 选择要遍历的提交源
            if use_remote and self.repo.remotes:
                try:
                    # 先获取最新的远程更新
                    logger.info("正在获取远程更新...")
                    origin = self.repo.remotes.origin
                    origin.fetch()
                    
                    # 尝试从远程master分支获取历史
                    remote_master = self.repo.remotes.origin.refs.master
                    commits_iter = self.repo.iter_commits(remote_master, max_count=limit)
                    logger.info(f"使用远程分支获取版本历史，限制: {limit}")
                except Exception as e:
                    logger.warning(f"无法从远程分支获取提交，回退到本地: {e}")
                    commits_iter = self.repo.iter_commits(max_count=limit)
            else:
                logger.info(f"使用本地分支获取版本历史，限制: {limit}")
                commits_iter = self.repo.iter_commits(max_count=limit)
            
            for commit in commits_iter:
                # 检查提交是否有标签
                tag = None
                for t in self.repo.tags:
                    if t.commit == commit:
                        tag = t.name
                        break
                
                versions.append(VersionInfo(
                    commit_hash=commit.hexsha[:8],
                    commit_message=commit.message.strip(),
                    author=commit.author.name,
                    date=datetime.fromtimestamp(commit.committed_date),
                    tag=tag,
                    is_current=(commit == current_commit)
                ))
            
            return versions
        except Exception as e:
            logger.error(f"获取版本历史失败: {e}")
            return []
    
    def get_tags(self) -> List[str]:
        """获取所有标签"""
        if not self.repo:
            return []
        
        try:
            tags = []
            for tag in self.repo.tags:
                tags.append(tag.name)
            
            # 按版本号排序（尝试语义化版本排序）
            try:
                from packaging import version
                tags.sort(key=lambda x: version.parse(x) if x.startswith('v') else x, reverse=True)
            except ImportError:
                tags.sort(reverse=True)
            
            return tags
        except Exception as e:
            logger.error(f"获取标签列表失败: {e}")
            return []
    
    def get_tags_with_info(self) -> List[TagInfo]:
        """获取带详细信息的标签列表"""
        if not self.repo:
            return []
        
        try:
            tags = []
            current_commit = self.repo.head.commit.hexsha
            
            for tag in self.repo.tags:
                tag_commit = tag.commit
                tags.append(TagInfo(
                    name=tag.name,
                    commit_hash=tag_commit.hexsha[:8],
                    message=tag_commit.message.strip(),
                    author=str(tag_commit.author),
                    date=tag_commit.committed_datetime,
                    is_current=(tag_commit.hexsha == current_commit)
                ))
            
            # 按日期排序（最新的在前）
            tags.sort(key=lambda x: x.date, reverse=True)
            
            return tags
        except Exception as e:
            logger.error(f"获取标签详细信息失败: {e}")
            return []
    
    def get_branches(self) -> List[BranchInfo]:
        """获取所有分支"""
        if not self.repo:
            return []
        
        try:
            branches = []
            current_branch = self.repo.active_branch.name if not self.repo.head.is_detached else None
            
            # 本地分支
            for branch in self.repo.branches:
                branches.append(BranchInfo(
                    name=branch.name,
                    commit_hash=branch.commit.hexsha[:8],
                    is_current=(branch.name == current_branch),
                    is_remote=False
                ))
            
            # 远程分支
            for remote in self.repo.remotes:
                for ref in remote.refs:
                    branch_name = f"{remote.name}/{ref.name.split('/')[-1]}"
                    if not any(b.name == branch_name for b in branches):
                        branches.append(BranchInfo(
                            name=branch_name,
                            commit_hash=ref.commit.hexsha[:8],
                            is_current=False,
                            is_remote=True
                        ))
            
            return branches
        except Exception as e:
            logger.error(f"获取分支列表失败: {e}")
            return []
    
    def switch_to_commit(self, commit_hash: str) -> Tuple[bool, str]:
        """切换到指定提交"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            # 检查是否有未提交的更改
            if self.repo.is_dirty():
                return False, "存在未提交的更改，请先提交或丢弃更改"
            
            # 切换到指定提交
            self.repo.git.checkout(commit_hash)
            
            return True, f"成功切换到提交 {commit_hash[:8]}"
        except Exception as e:
            logger.error(f"切换到提交 {commit_hash} 失败: {e}")
            return False, f"切换失败: {str(e)}"
    
    def switch_to_tag(self, tag_name: str) -> Tuple[bool, str]:
        """切换到指定标签"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            # 检查标签是否存在
            if tag_name not in [t.name for t in self.repo.tags]:
                return False, f"标签 {tag_name} 不存在"
            
            # 检查是否有未提交的更改
            if self.repo.is_dirty():
                return False, "存在未提交的更改，请先提交或丢弃更改"
            
            # 切换到标签
            self.repo.git.checkout(tag_name)
            
            return True, f"成功切换到标签 {tag_name}"
        except Exception as e:
            logger.error(f"切换到标签 {tag_name} 失败: {e}")
            return False, f"切换失败: {str(e)}"
    
    def switch_to_branch(self, branch_name: str) -> Tuple[bool, str]:
        """切换到指定分支"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            # 检查是否有未提交的更改
            if self.repo.is_dirty():
                return False, "存在未提交的更改，请先提交或丢弃更改"
            
            # 切换到分支
            self.repo.git.checkout(branch_name)
            
            return True, f"成功切换到分支 {branch_name}"
        except Exception as e:
            logger.error(f"切换到分支 {branch_name} 失败: {e}")
            return False, f"切换失败: {str(e)}"
    
    def pull_updates(self) -> Tuple[bool, str]:
        """拉取远程更新"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            # 检查是否有未提交的更改
            if self.repo.is_dirty():
                return False, "存在未提交的更改，请先提交或丢弃更改"
            
            # 拉取更新
            origin = self.repo.remotes.origin
            origin.pull()
            
            return True, "成功拉取远程更新"
        except Exception as e:
            logger.error(f"拉取更新失败: {e}")
            return False, f"拉取失败: {str(e)}"
    
    def fetch_updates(self) -> Tuple[bool, str]:
        """获取远程更新（不合并）"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            # 获取远程更新
            origin = self.repo.remotes.origin
            origin.fetch()
            
            return True, "成功获取远程更新"
        except Exception as e:
            logger.error(f"获取更新失败: {e}")
            return False, f"获取失败: {str(e)}"
    
    def check_for_updates(self) -> Tuple[bool, int]:
        """检查是否有可用更新"""
        if not self.repo:
            return False, 0
        
        try:
            # 先获取远程更新
            origin = self.repo.remotes.origin
            origin.fetch()
            
            # 计算本地分支落后多少提交
            current_branch = self.repo.active_branch
            remote_branch = origin.refs[current_branch.name]
            
            commits_behind = list(self.repo.iter_commits(f'{current_branch}..{remote_branch}'))
            
            return len(commits_behind) > 0, len(commits_behind)
        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            return False, 0
    
    def get_repo_status(self) -> Dict[str, any]:
        """获取仓库状态"""
        if not self.repo:
            return {"valid": False}
        
        try:
            current_version = self.get_current_version()
            has_updates, commits_behind = self.check_for_updates()
            
            return {
                "valid": True,
                "current_commit": current_version.commit_hash if current_version else None,
                "current_tag": current_version.tag if current_version else None,
                "branch": self.repo.active_branch.name if not self.repo.head.is_detached else "detached",
                "is_dirty": self.repo.is_dirty(),
                "has_updates": has_updates,
                "commits_behind": commits_behind,
                "remote_url": self.repo.remotes.origin.url if self.repo.remotes else None
            }
        except Exception as e:
            logger.error(f"获取仓库状态失败: {e}")
            return {"valid": False, "error": str(e)}
    
    def create_backup(self, backup_name: str = None) -> Tuple[bool, str]:
        """创建当前状态备份"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            if backup_name is None:
                backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # 创建备份分支
            backup_branch = self.repo.create_head(backup_name)
            
            return True, f"成功创建备份分支: {backup_name}"
        except Exception as e:
            logger.error(f"创建备份失败: {e}")
            return False, f"备份失败: {str(e)}"
    
    def list_backups(self) -> List[str]:
        """列出所有备份分支"""
        if not self.repo:
            return []
        
        try:
            backups = []
            for branch in self.repo.branches:
                if branch.name.startswith('backup_'):
                    backups.append(branch.name)
            
            return sorted(backups, reverse=True)
        except Exception as e:
            logger.error(f"列出备份失败: {e}")
            return []
    
    def restore_backup(self, backup_name: str) -> Tuple[bool, str]:
        """恢复备份"""
        if not self.repo:
            return False, "Git仓库未初始化"
        
        try:
            # 切换到备份分支
            self.repo.git.checkout(backup_name)
            
            return True, f"成功恢复到备份: {backup_name}"
        except Exception as e:
            logger.error(f"恢复备份 {backup_name} 失败: {e}")
            return False, f"恢复失败: {str(e)}"


# 全局版本管理实例
version_manager = VersionManager()