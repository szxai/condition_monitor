"""
任务列表解析器
负责解析外部任务列表JSON文件，提供任务与工况的映射关系
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Any


def parse_task_list(task_list_file: str) -> Dict[str, Any]:
    """
    解析任务列表JSON文件
    
    Args:
        task_list_file: 任务列表文件路径
        
    Returns:
        包含任务信息的字典，格式如下：
        {
            'task_map': {task_id: task_info},  # 任务ID到任务信息的映射
            'execution_order': [task_id1, task_id2, ...],  # 执行顺序
            'metadata': { ... }  # 元数据，包含源文件路径
        }
        
    Raises:
        FileNotFoundError: 文件不存在
        json.JSONDecodeError: JSON格式错误
        ValueError: 任务列表格式不符合要求
    """
    file_path = Path(task_list_file)
    if not file_path.exists():
        raise FileNotFoundError(f"任务列表文件不存在: {task_list_file}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 验证必要字段
    if 'tasks' not in data:
        raise ValueError("任务列表文件缺少 'tasks' 字段")
    
    if 'execution_order' not in data:
        raise ValueError("任务列表文件缺少 'execution_order' 字段")
    
    # 构建任务映射
    task_map = {}
    condition_to_tasks = {}
    
    for task in data['tasks']:
        if 'task_id' not in task:
            raise ValueError("任务缺少 'task_id' 字段")
        if 'condition_id' not in task:
            raise ValueError(f"任务 {task.get('task_id', '未知')} 缺少 'condition_id' 字段")
        
        task_id = task['task_id']
        if task_id in task_map:
            raise ValueError(f"任务ID重复: {task_id}")
        
        task_map[task_id] = task
        
        # 构建工况ID到任务列表的反向映射
        condition_id = task['condition_id']
        if condition_id not in condition_to_tasks:
            condition_to_tasks[condition_id] = []
        condition_to_tasks[condition_id].append(task_id)
    
    # 验证执行顺序中的任务ID都存在
    for task_id in data['execution_order']:
        if task_id not in task_map:
            raise ValueError(f"执行顺序中包含不存在的任务ID: {task_id}")
    
    # 复制元数据并添加源文件路径
    metadata = data.get('metadata', {})
    metadata['source_file'] = str(file_path.absolute())
    
    return {
        'tasks': data.get('tasks', []),
        'task_map': task_map,
        'condition_to_tasks': condition_to_tasks,
        'execution_order': data['execution_order'],
        'metadata': metadata
    }


def get_task_for_condition(condition_id: str, task_list_data: Dict[str, Any]) -> Optional[str]:
    """
    获取指定工况ID对应的下一个未执行任务ID
    
    Args:
        condition_id: 工况ID
        task_list_data: 任务列表数据
        
    Returns:
        未执行的任务ID，如果没有则返回None
    """
    # 这里需要结合任务执行状态来确定下一个任务
    # 暂时返回第一个匹配的任务ID
    condition_to_tasks = task_list_data.get('condition_to_tasks', {})
    if condition_id in condition_to_tasks and condition_to_tasks[condition_id]:
        return condition_to_tasks[condition_id][0]
    return None


def get_condition_for_task(task_id: str, task_list_data: Dict[str, Any]) -> Optional[str]:
    """
    获取指定任务ID对应的工况ID
    
    Args:
        task_id: 任务ID
        task_list_data: 任务列表数据
        
    Returns:
        工况ID，如果任务不存在则返回None
    """
    task_map = task_list_data.get('task_map', {})
    task = task_map.get(task_id)
    return task.get('condition_id') if task else None


def save_task_status(output_file: str, task_status: Dict[str, Any]):
    """
    保存任务状态到JSON文件
    
    Args:
        output_file: 输出文件路径
        task_status: 任务状态数据
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(task_status, f, ensure_ascii=False, indent=2)