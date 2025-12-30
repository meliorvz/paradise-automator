from playwright.sync_api import sync_playwright
import os
import time

def debug_preview_button():
    print("Starting Inspector...")
    print("1. Opening browser (using your profile)...")
    
    with sync_playwright() as p:
        # Launch with your profile
        browser = p.chromium.launch_persistent_context(
            user_data_dir=os.path.expanduser("~/.rei-browser-profile"),
            headless=False,
            viewport={"width": 1280, "height": 800}
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        print("2. Navigating to Reports...")
        page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758")
        
        print("\n=== INSTRUCTIONS ===")
        print("1. If not logged in, log in now.")
        print("2. Click 'Arrival Report'.")
        print("3. Click 'Tomorrow'.")
        print("4. WAIT until the 'Preview' popup is visible.")
        print("5. Then come back here and press ENTER.")
        input("Press ENTER when the Preview button is visible on screen...")
        
        print("\n=== INSPECTING PAGE ===")
        
        # Find anything with "Preview" text
        elements = page.locator("text=Preview").all()
        print(f"Found {len(elements)} elements with text 'Preview':")
        
        for i, el in enumerate(elements):
            try:
                if not el.is_visible():
                    continue
                    
                tag = el.evaluate("el => el.tagName")
                classes = el.get_attribute("class") or ""
                uid = el.get_attribute("id") or ""
                onclick = el.get_attribute("onclick") or ""
                html = el.evaluate("el => el.outerHTML")
                
                print(f"\n[Element {i}] Tag: {tag}")
                print(f"  Class: {classes}")
                print(f"  ID: {uid}")
                print(f"  HTML: {html[:200]}...") # First 200 chars
            except:
                pass
                
        print("\n=== SEARCHING FOR BUTTONS ===")
        btns = page.locator("button, a.btn, input[type='button'], div.btn").all()
        for i, el in enumerate(btns):
            try:
                if not el.is_visible(): continue
                text = el.inner_text()
                if "Preview" in text:
                    print(f"\n[Button Match {i}] Text: {text}")
                    print(f"  HTML: {el.evaluate('el => el.outerHTML')}")
            except:
                pass
                
        print("\nDone! Copy the output above.")
        input("Press Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    debug_preview_button()
