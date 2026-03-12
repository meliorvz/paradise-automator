import csv
with open("downloads/ArrivalReport (1).csv", "r", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    headers = next(reader)
    row1 = next(reader)
    for i, (h, v) in enumerate(zip(headers, row1)):
        print(f"{i}: {h} = {repr(v)}")
