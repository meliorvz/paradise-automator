import csv
import os
from api_email_sender import parse_csv

def verify_extraction_logic():
    # Create a mock CSV with real comments
    mock_csv = "mock_report.csv"
    headers = "textBox40,textBox39,textBox38,textBox37,textBox36,textBox35,textBox34,textBox27,textBox2,textBox3,textBox1,textBox5,textBox9,textBox11,textBox13,textBox15,textBox17,textBox22,textBox23,textBox31,textBox30,textBox29,textBox28,textBox26,textBox25,textBox24,textBox19,textBox20,textBox21,textBox32,textBox33,textBox12,textBox4,textBox6,textBox7,textBox8,textBox10,TrnReference1,textBox14,textBox16,textBox18".split(",")
    
    row = [""] * len(headers)
    d = {h: "" for h in headers}
    d["TrnReference1"] = "101"
    d["textBox4"] = "99999"
    d["textBox2"] = "Monday, 1 March 2026"
    d["textBox19"] = "Test Guest"
    d["textBox20"] = "Initial booking comments from guest."
    d["textBox32"] = "GC: This is a guest comment"
    d["textBox33"] = "MC: This is a manager comment"
    d["textBox16"] = "2B3"
    
    with open(mock_csv, "w", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow(d)
        
    print(f"--- Mock CSV created with comments ---")
    data = parse_csv(mock_csv)
    if data:
        entry = data[0]
        print(f"Room: {entry['room']}")
        print(f"Name: {entry['name']}")
        print(f"Extracted Comments: {entry['comments']}")
        
        # Verify specific expected behavior
        expected = "Initial booking comments from guest. | GC: This is a guest comment | MC: This is a manager comment"
        if entry['comments'] == expected:
            print("\n✅ SUCCESS: Comments extracted and concatenated properly!")
        else:
            print(f"\n❌ FAILURE: Expected '{expected}', got '{entry['comments']}'")
            
    os.remove(mock_csv)

if __name__ == "__main__":
    verify_extraction_logic()
