"""
将旧版工况坐标表转换为新版 ConditionExtendedTemplate.csv
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "referencePosition" / "ConditionExtendedTemplate.csv"

SOURCE_FILES = [
    (
        ROOT / "referencePosition" / "GD-PositionLabels-20221019.csv",
        "MainLine"
    ),
    (
        ROOT / "referencePosition" / "RegionLabels_4Points.csv",
        "Region"
    )
]

MAX_WAYPOINTS = 6
MAX_FORBIDDEN = 3
MAX_LOOP_ZONES = 3
DEFAULT_SKIP_DISTANCE = 200.0
DEFAULT_SKIP_TIME = 30.0


def parse_point(row: Dict[str, str], prefix: str) -> Optional[Tuple[float, float, float, float]]:
    keys = [f"{prefix}_LonLB", f"{prefix}_LonUB", f"{prefix}_LatLB", f"{prefix}_LatUB"]
    if not all(key in row and row[key].strip() for key in keys):
        return None

    try:
        lon_lb = float(row[keys[0]])
        lon_ub = float(row[keys[1]])
        lat_lb = float(row[keys[2]])
        lat_ub = float(row[keys[3]])
        return lon_lb, lon_ub, lat_lb, lat_ub
    except ValueError:
        return None


def append_waypoint(waypoints: List[Tuple[str, Tuple[float, float, float, float], bool]],
                    name: str,
                    row: Dict[str, str]):
    point = parse_point(row, name)
    if point:
        waypoints.append((name, point, True))


def convert_row(row: Dict[str, str], default_group: str) -> Dict[str, str]:
    condition = row.get("Condition", "").strip()
    if not condition:
        raise ValueError("Condition 不能为空")

    start = parse_point(row, "Start")
    if not start:
        raise ValueError(f"{condition} 缺少 Start 坐标")

    end = parse_point(row, "End") or parse_point(row, "Feature2") or parse_point(row, "Feature3") or start

    waypoints: List[Tuple[str, Tuple[float, float, float, float], bool]] = []
    for prefix in ("Feature1", "Feature2", "Feature3"):
        append_waypoint(waypoints, prefix, row)

    forbidden: List[Tuple[float, float, float, float]] = []
    feature4 = parse_point(row, "Feature4")
    if feature4:
        forbidden.append(feature4)

    output: Dict[str, str] = {
        "Condition": condition,
        "Description": row.get("Description", condition),
        "Group": row.get("Group", default_group),
        "Priority": str(int(float(row.get("Priority", 0) or 0))),
        "Ref_Time_Min": row.get("Ref_Time_Min", ""),
        "Ref_Time": row.get("Ref_Time", ""),
        "Ref_Time_Max": row.get("Ref_Time_Max", ""),
        "RequiredLaps": str(int(float(row.get("RequiredLaps", row.get("LapCount", 1) or 1)))),
        "Start_LonLB": f"{start[0]:.8f}",
        "Start_LonUB": f"{start[1]:.8f}",
        "Start_LatLB": f"{start[2]:.8f}",
        "Start_LatUB": f"{start[3]:.8f}",
        "End_LonLB": f"{end[0]:.8f}",
        "End_LonUB": f"{end[1]:.8f}",
        "End_LatLB": f"{end[2]:.8f}",
        "End_LatUB": f"{end[3]:.8f}",
        "SkipDistanceThresholdM": row.get("SkipDistanceThresholdM", str(DEFAULT_SKIP_DISTANCE)),
        "SkipTimeThresholdS": row.get("SkipTimeThresholdS", str(DEFAULT_SKIP_TIME)),
    }

    for idx in range(MAX_WAYPOINTS):
        prefix = f"Waypoint{idx + 1:02d}"
        if idx < len(waypoints):
            name, point, required = waypoints[idx]
            output[f"{prefix}_LonLB"] = f"{point[0]:.8f}"
            output[f"{prefix}_LonUB"] = f"{point[1]:.8f}"
            output[f"{prefix}_LatLB"] = f"{point[2]:.8f}"
            output[f"{prefix}_LatUB"] = f"{point[3]:.8f}"
            output[f"{prefix}_Required"] = "TRUE" if required else "FALSE"
        else:
            output[f"{prefix}_LonLB"] = ""
            output[f"{prefix}_LonUB"] = ""
            output[f"{prefix}_LatLB"] = ""
            output[f"{prefix}_LatUB"] = ""
            output[f"{prefix}_Required"] = ""

    for idx in range(MAX_LOOP_ZONES):
        prefix = f"LoopZone{idx + 1:02d}"
        output[f"{prefix}_LonLB"] = ""
        output[f"{prefix}_LonUB"] = ""
        output[f"{prefix}_LatLB"] = ""
        output[f"{prefix}_LatUB"] = ""
        output[f"{prefix}_Count"] = ""

    for idx in range(MAX_FORBIDDEN):
        prefix = f"Forbidden{idx + 1:02d}"
        if idx < len(forbidden):
            point = forbidden[idx]
            output[f"{prefix}_LonLB"] = f"{point[0]:.8f}"
            output[f"{prefix}_LonUB"] = f"{point[1]:.8f}"
            output[f"{prefix}_LatLB"] = f"{point[2]:.8f}"
            output[f"{prefix}_LatUB"] = f"{point[3]:.8f}"
        else:
            output[f"{prefix}_LonLB"] = ""
            output[f"{prefix}_LonUB"] = ""
            output[f"{prefix}_LatLB"] = ""
            output[f"{prefix}_LatUB"] = ""

    return output


def main():
    rows: List[Dict[str, str]] = []
    for file_path, group in SOURCE_FILES:
        with open(file_path, "r", encoding="utf-8-sig") as src:
            reader = csv.DictReader(src)
            for row in reader:
                try:
                    rows.append(convert_row(row, group))
                except ValueError as exc:
                    print(f"[WARN] 跳过 {row.get('Condition', '未知')}: {exc}")

    fieldnames = [
        "Condition", "Description", "Group", "Priority",
        "Ref_Time_Min", "Ref_Time", "Ref_Time_Max", "RequiredLaps",
        "Start_LonLB", "Start_LonUB", "Start_LatLB", "Start_LatUB",
        "End_LonLB", "End_LonUB", "End_LatLB", "End_LatUB",
    ]
    for idx in range(MAX_WAYPOINTS):
        prefix = f"Waypoint{idx + 1:02d}"
        fieldnames.extend([
            f"{prefix}_LonLB",
            f"{prefix}_LonUB",
            f"{prefix}_LatLB",
            f"{prefix}_LatUB",
            f"{prefix}_Required",
        ])
    for idx in range(MAX_LOOP_ZONES):
        prefix = f"LoopZone{idx + 1:02d}"
        fieldnames.extend([
            f"{prefix}_LonLB",
            f"{prefix}_LonUB",
            f"{prefix}_LatLB",
            f"{prefix}_LatUB",
            f"{prefix}_Count",
        ])
    for idx in range(MAX_FORBIDDEN):
        prefix = f"Forbidden{idx + 1:02d}"
        fieldnames.extend([
            f"{prefix}_LonLB",
            f"{prefix}_LonUB",
            f"{prefix}_LatLB",
            f"{prefix}_LatUB",
        ])
    fieldnames.extend(["SkipDistanceThresholdM", "SkipTimeThresholdS"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="") as dest:
        writer = csv.DictWriter(dest, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"[OK] 已写入 {OUTPUT} 共 {len(rows)} 条工况")


if __name__ == "__main__":
    main()


