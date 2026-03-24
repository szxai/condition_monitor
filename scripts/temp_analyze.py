import csv

def analyze():
    file_path = r'c:\Users\77010\0_SAIC\03_HardwareDevelop\02_ConditionMonitor\referencePosition\ConditionExtendedTemplate.csv'
    with open(file_path, 'r', encoding='gbk') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Condition'] in ['CY', 'AS']:
                print(f"{row['Condition']}:")
                for k, v in row.items():
                    if v and 'Loop' in k: print(f"  {k}: {v}")
                print(f"  Waypoint01: {row.get('Waypoint01_LonLB', '')}")
                print(f"  Waypoint02: {row.get('Waypoint02_LonLB', '')}")
                print(f"  Waypoint03: {row.get('Waypoint03_LonLB', '')}")
                print(f"  RequiredLaps: {row.get('RequiredLaps', '')}")

if __name__ == '__main__':
    analyze()
