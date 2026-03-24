import csv

def check_tw():
    file_path = r'c:\Users\77010\0_SAIC\03_HardwareDevelop\02_ConditionMonitor\referencePosition\ConditionExtendedTemplate.csv'
    with open(file_path, 'r', encoding='gbk') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if 'TW' in row['Condition']:
                print(f"Row {i+2}: {row['Condition']} -> Start: ({row['Start_LonLB']}, {row['Start_LatLB']})")

if __name__ == '__main__':
    check_tw()
