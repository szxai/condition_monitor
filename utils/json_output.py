"""
JSON输出工具
负责生成和保存工况状态的JSON输出
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

DEFAULT_STATUS_FILE = "output/status_output.json"


def generate_task_status_json(task_summary: Dict[str, Any], all_tasks_status: List[Dict[str, Any]], 
                            event_type: str = "task_completed") -> Dict[str, Any]:
    """
    生成任务状态JSON数据
    
    Args:
        task_summary: 当前完成任务的摘要信息
        all_tasks_status: 所有任务的状态列表
        event_type: 事件类型（task_completed, program_end, etc.）
        
    Returns:
        格式化的任务状态JSON数据
    """
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "current_task": task_summary,
        "all_tasks_status": all_tasks_status,
        "summary": {
            "total_tasks": len(all_tasks_status),
            "completed_tasks": sum(1 for task in all_tasks_status 
                                 if task.get("state") == "已完成"),
            "pending_tasks": sum(1 for task in all_tasks_status 
                                if task.get("state") == "未开始"),
            "failed_tasks": sum(1 for task in all_tasks_status 
                               if task.get("state") == "失败"),
            "skipped_tasks": sum(1 for task in all_tasks_status 
                                if task.get("state") == "已跳过")
        }
    }


def save_json_output(output_file: str, data: Dict[str, Any]):
    """
    保存JSON数据到文件
    
    Args:
        output_file: 输出文件路径
        data: 要保存的JSON数据
    """
    # 确保目录存在
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_json_output(data: Dict[str, Any]):
    """
    打印JSON数据到控制台
    
    Args:
        data: 要打印的JSON数据
    """
    print(json.dumps(data, ensure_ascii=False, indent=2))


def output_task_status(task_summary: Dict[str, Any], all_tasks_status: List[Dict[str, Any]], 
                      output_file: Optional[str] = None, print_to_console: bool = True):
    """
    输出任务状态（保存到文件和/或打印到控制台）
    
    Args:
        task_summary: 当前完成任务的摘要信息
        all_tasks_status: 所有任务的状态列表
        output_file: 输出文件路径，None表示使用默认路径
        print_to_console: 是否打印到控制台
    """
    # 生成JSON数据
    json_data = generate_task_status_json(task_summary, all_tasks_status)
    
    # 保存到文件
    if output_file or output_file is None:  # 如果明确指定为None，则不保存到文件
        file_path = output_file or DEFAULT_STATUS_FILE
        save_json_output(file_path, json_data)
    
    # 打印到控制台
    if print_to_console:
        print_json_output(json_data)