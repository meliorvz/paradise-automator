# REI Cloud Automation

Automate daily cleaning report generation from REI Cloud using Playwright.

## Prerequisites

- Python 3.8+
- pip

## Quick Start

### 1. Install Dependencies

```bash
pip install playwright python-dotenv
playwright install --with-deps
```

### 2. Login

Run the script manually to log in. The browser window will open.

```bash
python3 rei_cloud_automation.py
```

1. The browser will open using the profile at `~/.rei-browser-profile`.
2. Log in to REI Cloud manually.
3. Once logged in, you can close the browser or press ENTER in the terminal to start the automation.
4. Your session will be saved automatically for future runs.

### 4. Configure Email (Optional)

If you need to email the downloaded PDF:

```bash
cp .env.example .env
# Edit .env with your Gmail App Password
```

Create a Gmail App Password at: https://myaccount.google.com/apppasswords

### 5. Customize the Script

Edit `rei_cloud_automation.py`:
- Copy selectors from the generated code into the marked section
- Uncomment email sending if needed

### 6. Test

```bash
# First, test with visible browser
python rei_cloud_automation.py --headed

# Then test headless
python rei_cloud_automation.py
```

### 7. Schedule

See [docs/scheduling.md](docs/scheduling.md) for Mac/Linux/Windows instructions.

## File Structure

```
├── rei_cloud_automation.py  # Main script
├── api_email_sender.py      # API Email utility
├── .env                     # Your credentials (DO NOT COMMIT)
├── .env.example             # Template for .env
├── downloads/               # Downloaded PDFs
└── docs/
    ├── scheduling.md        # Scheduling instructions
    └── vps_migration.md     # VPS deployment guide
```

## Security Notes

- `.env` is in `.gitignore` by default
- Use Gmail App Password, not your main password
- Set `chmod 600` on sensitive files
- For VPS, use environment variables instead of `.env` file

## Refreshing Login Session

If your session expires:

Run the script manually to open the browser:
```bash
python3 rei_cloud_automation.py
# Log in again in the browser window
```
