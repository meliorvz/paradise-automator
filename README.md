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

### 2. Record Your Actions

This records your login session AND the steps to generate the report:

```bash
playwright codegen https://reimasterapps.com.au/Customers/Dashboard?reicid=758 --save-storage=auth.json
```

In the browser that opens:
1. Log in to REI Cloud
2. Navigate to the cleaning report section
3. Click buttons to generate/download the report
4. Close the browser when done

### 3. Secure the Session File

```bash
chmod 600 auth.json
```

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
├── email_sender.py          # Email utility
├── auth.json                # Session cookies (generated, DO NOT COMMIT)
├── .env                     # Your credentials (DO NOT COMMIT)
├── .env.example             # Template for .env
├── downloads/               # Downloaded PDFs
└── docs/
    ├── scheduling.md        # Scheduling instructions
    └── vps_migration.md     # VPS deployment guide
```

## Security Notes

- `auth.json` and `.env` are in `.gitignore` by default
- Use Gmail App Password, not your main password
- Set `chmod 600` on sensitive files
- For VPS, use environment variables instead of `.env` file

## Refreshing Login Session

If your session expires:

```bash
playwright codegen https://app.reicloud.com.au --save-storage=auth.json
# Log in again, then close the browser
chmod 600 auth.json
```
