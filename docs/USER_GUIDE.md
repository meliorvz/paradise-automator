# Paradise Automator - User Guide

A simple guide for the automated daily cleaning report system.

---

## 🎯 What Does This Do?

This tool **automatically downloads tomorrow's cleaning reports** from REI Cloud and **emails them to your cleaners every morning at 6:01 AM**.

Specifically, it:
1. Logs into REI Cloud (uses your saved login)
2. Downloads **Arrival** and **Departure** reports for tomorrow
3. Emails the reports to your cleaners with a summary table
4. Sends you an SMS + Telegram notification confirming delivery
5. Alerts you immediately if something goes wrong

**Result**: Your cleaners get an email every morning showing which properties need cleaning, without you lifting a finger.

---

## 🔄 How It Works

```
┌─────────────────┐      ┌──────────────┐      ┌─────────────────┐
│  REI Cloud      │ ---> │  Your Mac    │ ---> │  Cleaners'      │
│  (Reports)      │      │  (Automation)│      │  Email Inbox    │
└─────────────────┘      └──────────────┘      └─────────────────┘
                                │
                                v
                         ┌──────────────┐
                         │  You (SMS +  │
                         │  Telegram)   │
                         └──────────────┘
```

Every day at 6:01 AM:
1. The script opens a hidden browser and uses your saved login session
2. Navigates to Reports → Arrival Report → selects "Tomorrow" → downloads PDF & CSV
3. Does the same for the Departure Report
4. Reads the CSV files to create a nice summary table with room types, guest counts, and check-in/check-out times
5. Sends an email with the summary table + attached PDFs
6. Sends an SMS summary to the configured sender phone
7. Posts a delivery status report to Telegram
8. Notifies you via SMS and Telegram if anything failed

**Plus**: Every hour, the script checks that your REI Cloud session is still active (heartbeat check) and alerts you if it expires.

---

## 📋 Operating Instructions

### First-Time Setup

1. **Open Terminal** and navigate to the project folder:
   ```
   cd /Users/victor/Documents/paradise-automator
   ```

2. **Start the automation**:
   ```
   ./run.sh --run-now
   ```

3. **A browser window opens** → Log into REI Cloud manually

4. **Once logged in**, switch back to Terminal and **press ENTER**

5. The script will run immediately once (because of `--run-now`), then stay running for the daily schedule

### Daily Use

| Scenario | What to Do |
|----------|------------|
| **Normal operation** | Leave the Terminal window running. It runs automatically at 6:01 AM. |
| **Run manually right now** | In the Terminal, just press **ENTER** |
| **Stop the automation** | Press **Ctrl+C** in the Terminal |
| **Restart after computer reboot** | Run `./run.sh --run-now` and log in again |

### Command Options

| Command | What It Does |
|---------|--------------|
| `./run.sh` | Runs at 6:01 AM daily |
| `./run.sh --run-now` | Runs immediately once, then daily at 6:01 AM |
| `./run.sh --test` | Runs every 5 minutes (for testing only) |
| `./run.sh --record` | Debug mode - logs visited pages |

### Checking If It's Working

- Look at Terminal for green checkmarks (✓)
- Look for the email in your inbox
- Check Telegram for the delivery confirmation message

---

## ⚠️ Vulnerabilities & Pitfalls

### Things That Will Break It

| Problem | What Happens | How to Fix |
|---------|--------------|------------|
| **Mac goes to sleep** | Automation stops | Disable sleep in System Settings → Energy |
| **Terminal is closed** | Automation stops | Keep Terminal window open (minimized is OK) |
| **REI Cloud changes its website** | Downloads fail | Contact your developer |
| **Login expires** | Can't access reports | Restart with `./run.sh --run-now` and log in again |
| **Internet goes down** | Can't reach REI Cloud | It will retry, but check your connection |
| **Power outage** | Everything stops | Restart after power returns |

### Session & Login Issues

> [!IMPORTANT]
> **The script now automatically checks your login session every hour** (heartbeat check). If your session expires, you'll get an SMS/Telegram alert immediately.
> 
> When alerted:
> 1. Stop the automation (`Ctrl+C`)
> 2. Restart with `./run.sh --run-now`
> 3. Log into REI Cloud again in the browser
> 4. Press ENTER to continue

### Other Limitations

- **One computer only**: The automation runs on this specific Mac
- **Must stay on**: Your Mac needs to be running 24/7
- **Not instant**: If you need a report right now, do it manually in REI Cloud
- **Email failures**: If emails fail, you get SMS/Telegram alerts - check the log file

### If Something Goes Wrong

1. **Check Terminal** for error messages
2. **Check `automation.log`** in the project folder for detailed history
3. **You will receive an SMS/Telegram alert** if the scheduled run fails

---

## 📤 Who Gets the Reports?

Configured in your `.env` file:

| Setting | Purpose | Example |
|---------|---------|---------|
| `EMAIL_TO` | Main recipients (cleaners) | cleaner1@email.com, cleaner2@email.com |
| `EMAIL_CC` | CC recipients (managers) | manager@email.com |
| `SMS_SENDER_NOTIFY` | Your phone for confirmations | +61412345678 |
| `ESCALATION_PHONE` | Emergency alerts if it fails | +61412345678 |

---

## 🆘 Quick Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| No email received | Email sending failed | Check Terminal for errors |
| "Session expired" error | Login timed out | Restart and log in again |
| Browser not opening | Playwright issue | Run `python3 -m playwright install` |
| "No recipients" error | EMAIL_TO not set | Check your `.env` file |
| Slow/hanging | Poor internet | Wait, or restart the automation |

---

**Need help?** Check the `automation.log` file or contact your developer.
