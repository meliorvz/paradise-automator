import csv
import json

with open("downloads/ArrivalReport (1).csv", "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    if rows:
        # Print all headers
        print("Headers:", reader.fieldnames)
        # Check if any row has non-empty textBox32 or textBox33 beyond the prefix
        for i, row in enumerate(rows):
            for k, v in row.items():
                if v and "MC:" in v and len(v) > 3:
                    print(f"Row {i} - {k}: {v}")
                if v and "GC:" in v and len(v) > 3:
                    print(f"Row {i} - {k}: {v}")
            # Also just print a full row to see if anything looks like a comment but is in another field
            if i == 0:
                print("\nFull Row 0:")
                for k, v in row.items():
                    print(f"  {k}: {repr(v)}")
