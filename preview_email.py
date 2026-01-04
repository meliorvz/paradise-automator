
import sys
import os

# Add current dir to path to import api_email_sender
sys.path.append(os.getcwd())

from api_email_sender import parse_csv

def generate_preview(arrivals_path, departures_path):
    arrivals_data = parse_csv(arrivals_path)
    departures_data = parse_csv(departures_path)
    
    print("\n--- EMAIL PREVIEW (Text Version) ---\n")
    
    print(f"**Arrivals ({len(arrivals_data)})**")
    print("| Room | Type | Guest | Guests | Check-in |")
    print("|---|---|---|---|---|")
    for r in arrivals_data:
        pax = f"{r['adults']}A {r['children']}C {r['infants']}I"
        print(f"| **{r['room']}** | {r['room_type']} | {r['name']} | {pax} | {r.get('time', '-') or '-'} |")
        
    print("\n")
    
    print(f"**Departures ({len(departures_data)})**")
    print("| Room | Type | Guest | Guests | Check-out |")
    print("|---|---|---|---|---|")
    for r in departures_data:
        pax = f"{r['adults']}A {r['children']}C {r['infants']}I"
        print(f"| **{r['room']}** | {r['room_type']} | {r['name']} | {pax} | {r.get('time', '-') or '-'} |")

if __name__ == "__main__":
    generate_preview("downloads/arrivals_20251231.csv", "downloads/departures_20251231.csv")
