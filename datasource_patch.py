
# 插件数据源修复补丁
# 在启动器后端中使用修复后的数据

def get_fixed_plugin_data():
    """获取修复后的插件数据"""
    import os
    import json

    # 尝试使用本地修复版本
    backup_dir = os.path.join(os.path.dirname(__file__), 'datasource_backup')
    fixed_file = os.path.join(backup_dir, 'custom-node-list-fixed-latest.json')

    if os.path.exists(fixed_file):
        try:
            with open(fixed_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取修复数据失败: {e}")

    return None

# 在get_available_nodes_from_network函数中优先使用修复数据
