import csv
import sys

# Try different encodings
encodings = ['utf-8-sig', 'latin-1', 'utf-16']
for enc in encodings:
    try:
        with open("/Users/victor/Documents/paradise-automator/downloads/ArrivalReport (1).csv", "r", encoding=enc) as f:
            reader = csv.reader(f)
            headers = next(reader)
            print(f"--- Encoding: {enc} ---")
            print("Headers:", headers)
            for i, row in enumerate(reader):
                if i > 2: break
                print(f"Row {i}: {row}")
            break
    except Exception as e:
        print(f"Failed with {enc}: {e}")

