"""
工况监控系统主程序
"""
import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from gps.gps_reader import create_gps_reader
from monitor.task_manager import TaskManager
from utils.command_listener import CommandListener
from utils.condition_parser import ConditionParser
from utils.task_list_parser import parse_task_list
from utils.logger import setup_logger

# Initialize logger
logger = setup_logger("ConditionMonitorCLI")

# Global Exception Hook
def exception_hook(exctype, value, traceback):
    logger.critical("Uncaught exception", exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)

sys.excepthook = exception_hook

DEFAULT_TASK_OPTIONS = {
    'mode': 'sequential',
    'preferred_conditions': [],
    'auto_skip': {
        'enabled': True,
        'distance_threshold_m': 200.0,
        'time_threshold_s': 30.0
    }
}

DEFAULT_UI_OPTIONS = {
    'interactive_commands': True
}


class ConditionMonitorSystem:
    """工况监控系统主类"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化系统
        
        Args:
            config_path: 配置文件路径（可选）
        """
        self.config = self._load_config(config_path)
        self.gps_reader = None
        self.task_manager = None
        self.task_list_data = None
        self.running = False
        self.command_listener: Optional[CommandListener] = None
    
    def _load_config(self, config_path: Optional[str]) -> dict:
        """加载配置文件"""
        base_config = {
            'gps': {
                'mode': 'auto',
                'port': '/dev/ttyACM0',
                'baudrate': 115200,
                'csv_file': None,
                'rate': 10.0  # 提高GPS数据更新频率到每秒10次
            },
            'conditions': {
            'file': 'referencePosition/GD-PositionLabels-20221019.csv'
        },
            'task_list': [],
            'task_options': DEFAULT_TASK_OPTIONS,
            'ui': DEFAULT_UI_OPTIONS
        }

        loaded = {}
        if config_path and Path(config_path).exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

        config = copy.deepcopy(base_config)
        if loaded:
            config['gps'].update(loaded.get('gps', {}))
            config['conditions']['file'] = loaded.get('conditions', {}).get(
                'file',
                config['conditions']['file']
            )
            config['task_list'] = loaded.get('task_list', config['task_list'])
            # 添加对task_list_file配置的加载
            if 'task_list_file' in loaded:
                config['task_list_file'] = loaded['task_list_file']
            # 添加对status_output_file配置的加载
            if 'status_output_file' in loaded:
                config['status_output_file'] = loaded['status_output_file']

        task_options_src = loaded.get('task_options', {})
        merged_task_options = copy.deepcopy(DEFAULT_TASK_OPTIONS)
        merged_task_options.update({k: v for k, v in task_options_src.items() if k != 'auto_skip'})
        auto_skip = copy.deepcopy(DEFAULT_TASK_OPTIONS['auto_skip'])
        auto_skip.update(task_options_src.get('auto_skip', {}))
        merged_task_options['auto_skip'] = auto_skip
        config['task_options'] = merged_task_options

        ui_options = copy.deepcopy(DEFAULT_UI_OPTIONS)
        ui_options.update(loaded.get('ui', {}))
        config['ui'] = ui_options
        return config
    
    def initialize(self):
        """初始化系统组件"""
        logger.info("Initializing ConditionMonitorSystem")
        print("=" * 60)
        print("工况监控系统初始化中...")
        print("=" * 60)
        
        # 初始化GPS读取器
        gps_config = self.config['gps']
        print(f"GPS模式: {gps_config['mode']}")
        
        try:
            self.gps_reader = create_gps_reader(
                mode=gps_config['mode'],
                port=gps_config.get('port', '/dev/ttyACM0'),
                baudrate=gps_config.get('baudrate', 115200),
                csv_file=gps_config.get('csv_file'),
                rate=gps_config.get('rate', 1.0)
            )
            logger.info(f"GPS Reader initialized: {gps_config['mode']}")
            print("✓ GPS读取器初始化成功")
        except Exception as e:
            logger.critical(f"GPS Reader initialization failed: {e}", exc_info=True)
            print(f"✗ GPS读取器初始化失败: {e}")
            sys.exit(1)
        
        # 加载工况定义
        conditions_file = self.config['conditions']['file']
        print(f"加载工况定义文件: {conditions_file}")
        
        try:
            all_conditions = ConditionParser.parse_csv(conditions_file)
            print(f"✓ 成功加载 {len(all_conditions)} 个工况定义")
        except Exception as e:
            print(f"✗ 加载工况定义失败: {e}")
            sys.exit(1)
        
        # 加载外部任务列表（如果配置了）
        task_list_file = self.config.get('task_list_file')
        if task_list_file:
            try:
                self.task_list_data = parse_task_list(task_list_file)
                print(f"✓ 加载外部任务列表，包含 {len(self.task_list_data.get('execution_order', []))} 个任务")
            except Exception as e:
                print(f"✗ 加载外部任务列表失败: {e}")
                sys.exit(1)
        else:
            print("未配置外部任务列表，使用配置文件中的任务列表")
        
        # 根据任务列表筛选工况
        task_list = self.config.get('task_list', [])
        
        # 优先使用外部任务列表数据（如果有）
        if self.task_list_data:
            # 修改：将 condition_map 改为列表的字典，防止同名工况（如 TW-1, TW-2 解析后都叫 TW）被覆盖
            condition_map = {}
            for cond in all_conditions:
                if cond.condition_name not in condition_map:
                    condition_map[cond.condition_name] = []
                condition_map[cond.condition_name].append(cond)
                
            selected_conditions = []
            
            # 从execution_order中获取所有任务，然后从task_map中获取对应的condition_id
            task_ids = self.task_list_data.get('execution_order', [])
            task_map = self.task_list_data.get('task_map', {})
            
            for task_id in task_ids:
                if task_id in task_map:
                    condition_id = task_map[task_id].get('condition_id')
                    if condition_id in condition_map:
                        # 将所有同名工况加入 selected_conditions
                        selected_conditions.extend(condition_map[condition_id])
                    else:
                        print(f"警告: 任务 {task_id} 引用了未定义的工况: {condition_id}")
                else:
                    print(f"警告: 执行顺序中包含未在任务映射中定义的任务: {task_id}")
            
            conditions = selected_conditions
            print(f"根据外部任务列表筛选出 {len(conditions)} 个工况")
        # 其次使用配置文件中的任务列表
        elif task_list:
            # 使用指定的任务列表
            condition_map = {}
            for cond in all_conditions:
                if cond.condition_name not in condition_map:
                    condition_map[cond.condition_name] = []
                condition_map[cond.condition_name].append(cond)
                
            selected_conditions = []
            for task_name in task_list:
                if task_name in condition_map:
                    selected_conditions.extend(condition_map[task_name])
                else:
                    print(f"警告: 任务列表中包含未定义的工况: {task_name}")
            conditions = selected_conditions
        else:
            # 使用所有工况
            conditions = all_conditions
        
        print(f"任务列表包含 {len(conditions)} 个工况:")
        for i, cond in enumerate(conditions, 1):
            print(f"  {i}. {cond.condition_name}")
        
        # 初始化任务管理器
        task_options = self.config.get('task_options', DEFAULT_TASK_OPTIONS)
        scheduler_mode = task_options.get('mode', 'sequential')
        preferred = task_options.get('preferred_conditions', [])
        auto_skip_cfg = task_options.get('auto_skip', DEFAULT_TASK_OPTIONS['auto_skip'])

        try:
            self.task_manager = TaskManager(
                conditions,
                scheduler_mode=scheduler_mode,
                preferred_conditions=preferred,
                auto_skip=auto_skip_cfg,
                task_list_data=self.task_list_data,
                status_output_file=self.config.get('status_output_file', 'output/task_status.json')
            )
            print("✓ 任务管理器初始化成功")
        except Exception as e:
            print(f"✗ 任务管理器初始化失败: {e}")
            sys.exit(1)
        
        if self.config.get('ui', {}).get('interactive_commands', True):
            self._start_command_listener()

        print("=" * 60)
        print("系统初始化完成，开始监控...")
        print(f"调度模式: {scheduler_mode} | 自动跳过: {'启用' if auto_skip_cfg.get('enabled', True) else '关闭'}")
        if self.command_listener:
            print("交互命令已开启，输入 help 查看可用命令。")
        print("=" * 60)
        print()
    
    def run(self):
        """运行监控循环"""
        if not self.gps_reader or not self.task_manager:
            print("错误: 系统未初始化")
            return
        
        self.running = True
        last_status_time = time.time()
        status_interval = 1.0  # 每1秒输出一次状态摘要
        
        try:
            while self.running:
                self._process_commands()

                # 读取GPS数据 (快速读取所有可用数据以减少延迟)
                gps = self.gps_reader.read()
                
                if gps:
                    # 更新任务状态
                    update_info = self.task_manager.update(gps)
                    
                    # 如果状态发生变化，立即输出
                    if update_info.get('state_changed', False) or update_info.get('last_summary'):
                        self._print_update(update_info, gps)
                    
                    # 定期输出状态摘要
                    current_time = time.time()
                    if current_time - last_status_time >= status_interval:
                        self._print_status_summary()
                        last_status_time = current_time
                
                # 控制循环频率，提高主程序刷新率以降低识别延迟 (从 100ms 降低到 50ms)
                time.sleep(0.05)
        
        except KeyboardInterrupt:
            print("\n\n收到中断信号，正在停止...")
            logger.info("Stopped by user (KeyboardInterrupt)")
        except Exception as e:
            logger.error(f"Runtime error: {e}", exc_info=True)
            print(f"\n\n发生错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def _print_update(self, update_info: dict, gps):
        """打印状态更新信息"""
        print(f"\n[{gps.timestamp.strftime('%H:%M:%S')}] GPS: ({gps.longitude:.6f}, {gps.latitude:.6f})")
        if update_info.get('state_changed'):
            print(f"  状态变化: {update_info.get('old_state')} -> {update_info.get('new_state')}")
        print(f"  {update_info.get('message', '')}")
        
        if update_info.get('current_task'):
            task_info = update_info['current_task']
            print(f"  当前工况: {task_info['condition']}")
            if task_info.get('description'):
                print(f"    描述: {task_info['description']}")
            laps = task_info.get('laps_completed')
            required_laps = task_info.get('required_laps')
            if required_laps and (required_laps > 1 or laps):
                print(f"    圈数: {laps or 0}/{required_laps}")
            for checkpoint in task_info.get('checkpoints', []):
                mark = '✓' if checkpoint.get('passed') else '…'
                req = '必经' if checkpoint.get('required') else '参考'
                print(f"    {checkpoint.get('name'):<10} [{req}] {mark}")
            if task_info.get('loop_zones'):
                for loop in task_info['loop_zones']:
                    current = loop.get('current_entries', 0)
                    required = loop.get('required_entries', 0)
                    print(f"    循环区 {loop.get('name')}: {current}/{required}")
        
        if update_info.get('last_summary'):
            self._print_summary(update_info['last_summary'])

    def _print_summary(self, summary: dict, indent: str = "  "):
        print(f"{indent}--- 执行结果 ---")
        print(f"{indent}状态: {summary.get('state')} ({summary.get('result')})")
        print(f"{indent}起止时间: {summary.get('start_time')} -> {summary.get('end_time')}")
        if summary.get('duration_seconds') is not None:
            print(f"{indent}历时: {summary['duration_seconds']:.1f}s")
        if summary.get('required_laps'):
            laps = summary.get('laps_completed', 0)
            print(f"{indent}圈数: {laps}/{summary.get('required_laps')}")
        if summary.get('avg_speed_kmh') is not None:
            avg = f"{summary['avg_speed_kmh']:.1f}"
            max_speed = summary.get('max_speed_kmh')
            min_speed = summary.get('min_speed_kmh')
            max_text = f"{max_speed:.1f}" if max_speed is not None else "--"
            min_text = f"{min_speed:.1f}" if min_speed is not None else "--"
            print(f"{indent}平均/最高/最低速度: {avg} / {max_text} / {min_text} km/h")
        if summary.get('distance_m') is not None:
            print(f"{indent}行驶距离: {summary['distance_m']:.1f} m")
        if summary.get('loop_zones'):
            for loop in summary['loop_zones'] or []:
                current = loop.get('current_entries', 0)
                required = loop.get('required_entries', 0)
                print(f"{indent}循环区 {loop.get('name')}: {current}/{required}")
        if summary.get('skip_reason'):
            print(f"{indent}跳过原因: {summary['skip_reason']}")
        if summary.get('failure_reason'):
            print(f"{indent}失败原因: {summary['failure_reason']}")
    
    def _print_status_summary(self, detail: bool = False):
        """打印状态摘要"""
        status = self.task_manager.get_status()
        print(f"\n--- 状态摘要 ---")
        print(f"总任务数: {status['total_tasks']}")
        print(f"已完成: {len(status['completed_tasks'])}")
        print(f"剩余: {status['remaining_tasks']}")

        if status['current_task']:
            task = status['current_task']
            print(f"当前工况: {task['condition']} - {task['state']}")
        else:
            print("当前无执行中的工况")

        if detail:
            if status['pending_tasks']:
                print(f"待执行: {', '.join(status['pending_tasks'])}")
            if status['completed_tasks']:
                print(f"已完成工况: {', '.join(status['completed_tasks'])}")
            if status['execution_log']:
                print("最近完成记录:")
                for entry in status['execution_log']:
                    self._print_summary(entry, indent="    ")

        print("-" * 20)
    
    def cleanup(self):
        """清理资源并输出最终总结"""
        print("\n清理系统资源...")
        
        # 输出最终工况状态总结
        if self.task_manager:
            print("\n输出最终工况状态总结...")
            self.task_manager.output_final_summary()
        
        if self.command_listener:
            self.command_listener.stop()
        if self.gps_reader:
            self.gps_reader.close()
        print("系统已关闭。")

    def _start_command_listener(self):
        self.command_listener = CommandListener()
        self.command_listener.start()

    def _process_commands(self):
        if not self.command_listener:
            return
        command = self.command_listener.get_next_command()
        while command:
            self._handle_command(command)
            command = self.command_listener.get_next_command()

    def _handle_command(self, command: str):
        cmd, *rest = command.strip().split(' ', 1)
        cmd = cmd.lower()
        arg = rest[0].strip() if rest else ""

        if cmd in ('help', '?'):
            self._print_command_help()
        elif cmd == 'status':
            self._print_status_summary(detail=True)
        elif cmd == 'skip':
            reason = arg or "人工跳过"
            summary = self.task_manager.skip_current(reason=reason, requeue=True)
            if summary:
                print(f"\n已跳过当前工况，原因: {reason}")
                self._print_summary(summary)
            else:
                print("当前没有正在执行的工况，无法跳过。")
        elif cmd == 'complete':
            reason = arg or "人工完成"
            summary = self.task_manager.complete_current(reason=reason)
            if summary:
                print(f"\n已手动完成当前工况，原因: {reason}")
                self._print_summary(summary)
            else:
                print("当前没有正在执行的工况，无法手动完成。")
        elif cmd == 'log':
            status = self.task_manager.get_status()
            if not status['execution_log']:
                print("暂无执行记录。")
            else:
                print("\n--- 历史记录 ---")
                for entry in status['execution_log']:
                    self._print_summary(entry, indent="    ")
        elif cmd == 'next':
            status = self.task_manager.get_status()
            pending = status['pending_tasks']
            print(f"待执行队列: {', '.join(pending) if pending else '无'}")
        elif cmd == 'exit':
            print("收到退出命令，即将停止监控...")
            self.running = False
        else:
            print(f"未知命令: {command}. 输入 help 查看可用命令。")

    def _print_command_help(self):
        print("\n可用命令：")
        print("  help           显示命令帮助")
        print("  status         输出当前状态与执行记录")
        print("  skip [原因]    人工跳过当前工况（放至队尾）")
        print("  complete [原因] 手动完成当前工况")
        print("  log            查看最近的执行/跳过记录")
        print("  next           查看待执行工况队列")
        print("  exit           停止监控程序")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='工况监控系统')
    parser.add_argument(
        '--config',
        type=str,
        default='config/config.json',
        help='配置文件路径（默认: config/config.json）'
    )
    parser.add_argument(
        '--gps-mode',
        type=str,
        choices=['auto', 'usb', 'csv'],
        help='GPS读取模式（覆盖配置文件）'
    )
    parser.add_argument(
        '--csv-file',
        type=str,
        help='GPS CSV文件路径（CSV模式）'
    )
    parser.add_argument(
        '--rate',
        type=float,
        help='CSV读取速率（每秒行数）'
    )
    parser.add_argument(
        '--conditions-file',
        type=str,
        help='工况定义文件路径（覆盖配置文件）'
    )
    parser.add_argument(
        '--task-mode',
        type=str,
        choices=['sequential', 'nearest', 'priority'],
        help='任务调度模式'
    )
    parser.add_argument(
        '--preferred',
        type=str,
        help='优先执行的工况名称（逗号分隔）'
    )
    parser.add_argument(
        '--auto-skip-distance',
        type=float,
        help='自动跳过距离阈值（米）'
    )
    parser.add_argument(
        '--auto-skip-time',
        type=float,
        help='自动跳过持续时间阈值（秒）'
    )
    parser.add_argument(
        '--disable-auto-skip',
        action='store_true',
        help='禁用自动跳过逻辑'
    )
    parser.add_argument(
        '--no-interactive',
        action='store_true',
        help='禁用交互命令监听'
    )
    
    args = parser.parse_args()
    
    # 创建系统实例
    system = ConditionMonitorSystem(config_path=args.config)
    
    # 应用命令行参数覆盖
    if args.gps_mode:
        system.config['gps']['mode'] = args.gps_mode
    if args.csv_file:
        system.config['gps']['csv_file'] = args.csv_file
    if args.rate:
        system.config['gps']['rate'] = args.rate
    if args.conditions_file:
        system.config['conditions']['file'] = args.conditions_file
    if args.no_interactive:
        system.config.setdefault('ui', {})['interactive_commands'] = False
    task_options = system.config.setdefault('task_options', DEFAULT_TASK_OPTIONS.copy())
    if args.task_mode:
        task_options['mode'] = args.task_mode
    if args.preferred:
        task_options['preferred_conditions'] = [item.strip() for item in args.preferred.split(',') if item.strip()]
    auto_skip_cfg = task_options.setdefault('auto_skip', DEFAULT_TASK_OPTIONS['auto_skip'].copy())
    if args.disable_auto_skip:
        auto_skip_cfg['enabled'] = False
    if args.auto_skip_distance:
        auto_skip_cfg['distance_threshold_m'] = args.auto_skip_distance
    if args.auto_skip_time:
        auto_skip_cfg['time_threshold_s'] = args.auto_skip_time
    
    # 初始化和运行
    system.initialize()
    system.run()


if __name__ == '__main__':
    main()

