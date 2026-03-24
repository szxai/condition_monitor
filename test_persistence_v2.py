
import unittest
import os
import json
import shutil
from datetime import datetime, timedelta
from monitor.task_manager import TaskManager
from monitor.condition_monitor import ConditionState
from models.condition import ConditionDefinition, GPSPoint, PathCheckpoint
from models.gps_data import GPSData

class TestTaskPersistence(unittest.TestCase):
    def setUp(self):
        # Setup temporary directories
        self.test_dir = 'test_persistence_temp'
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Mock task list file
        self.task_list_file = os.path.join(self.test_dir, 'tasks_list.json')
        self.task_status_file = os.path.join(self.test_dir, 'task_status.json')
        
        self.task_list_data = {
            "execution_order": ["TASK-001", "TASK-002"],
            "task_map": {
                "TASK-001": {
                    "task_id": "TASK-001",
                    "condition_id": "COND-1",
                    "name": "Task 1",
                    "state": "pending"
                },
                "TASK-002": {
                    "task_id": "TASK-002",
                    "condition_id": "COND-2",
                    "name": "Task 2",
                    "state": "pending"
                }
            }
        }
        
        # Helper to create GPSPoint
        def make_point(lat, lon, r=0):
            return GPSPoint(lon-0.001, lon+0.001, lat-0.001, lat+0.001)

        # Mock conditions
        self.conditions = [
            ConditionDefinition(
                condition_name="COND-1",
                description="Test Condition 1",
                start=make_point(30.0, 120.0),
                end=make_point(30.01, 120.01),
                checkpoints=[
                    PathCheckpoint("CP1", make_point(30.005, 120.005), required=True)
                ],
                required_laps=2,
                ref_time_min=60,
                ref_time=120,
                ref_time_max=180
            ),
            ConditionDefinition(
                condition_name="COND-2",
                description="Test Condition 2",
                start=make_point(31.0, 121.0),
                end=make_point(31.01, 121.01),
                required_laps=1,
                ref_time_min=60,
                ref_time=120,
                ref_time_max=180
            )
        ]

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_persistence_flow(self):
        # 1. Initialize TaskManager
        tm = TaskManager(
            conditions=self.conditions,
            task_list_data=self.task_list_data
        )
        # Override status file path for testing
        tm.task_status_file = self.task_status_file
        tm._load_task_status() # Reload empty status
        
        # 2. Start Task 1
        # GPSData(timestamp, longitude, latitude, altitude, speed, heading)
        # Note: Argument order matters if not keyword args! 
        # dataclass default order is fields as defined.
        # GPSData: timestamp, longitude, latitude, altitude, speed, heading
        gps_start = GPSData(datetime.now(), 120.0, 30.0, 0, 0)
        tm.update(gps_start)
        
        self.assertEqual(tm.current_monitor.task_id, "TASK-001")
        self.assertEqual(tm.current_monitor.state, ConditionState.IN_PROGRESS)
        
        # Check if status file created and contains IN_PROGRESS
        self.assertTrue(os.path.exists(self.task_status_file))
        with open(self.task_status_file, 'r', encoding='utf-8') as f:
            status = json.load(f)
            self.assertIn("TASK-001", status)
            self.assertEqual(status["TASK-001"]["state"], "in_progress")
            
        # 3. Simulate progress (Pass Checkpoint 1)
        gps_cp1 = GPSData(datetime.now(), 120.005, 30.005, 0, 0)
        tm.update(gps_cp1)
        
        # Check status file for checkpoint
        with open(self.task_status_file, 'r', encoding='utf-8') as f:
            status = json.load(f)
            checkpoints = status["TASK-001"]["checkpoints"]
            self.assertTrue(checkpoints[0]["passed"])
            
        # 4. Simulate Lap Completion
        # First reach end -> enters COMPLETING, then a later timestamp triggers completion
        t0 = datetime.now()
        gps_end = GPSData(t0, 120.01, 30.01, 0, 0)
        tm.update(gps_end)
        gps_end_later = GPSData(t0 + timedelta(seconds=0.2), 120.01, 30.01, 0, 0)
        tm.update(gps_end_later)
        
        self.assertEqual(tm.current_monitor.completed_laps, 1)
        
        # Check status file for laps
        with open(self.task_status_file, 'r', encoding='utf-8') as f:
            status = json.load(f)
            self.assertEqual(status["TASK-001"]["laps_completed"], 1)
            
        # 5. Simulate Crash/Restart
        # Create new TaskManager instance
        tm2 = TaskManager(
            conditions=self.conditions,
            task_list_data=self.task_list_data
        )
        tm2.task_status_file = self.task_status_file
        tm2._load_task_status() # Load persisted status
        
        # Update with arbitrary GPS to trigger selection
        tm2.update(gps_start)
        
        # Verify state restoration
        self.assertEqual(tm2.current_monitor.task_id, "TASK-001")
        self.assertEqual(tm2.current_monitor.state, ConditionState.IN_PROGRESS)
        self.assertEqual(tm2.current_monitor.completed_laps, 1)
        self.assertFalse(tm2.current_monitor.checkpoint_status["CP1"])
        
        print("Persistence Test Passed!")

if __name__ == '__main__':
    unittest.main()
