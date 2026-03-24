
try:
    from monitor.condition_monitor import ConditionState
    print(f"Verified: {ConditionState.MANUAL_COMPLETED}")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
