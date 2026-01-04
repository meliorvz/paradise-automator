# REI Cloud Automation - Running Instructions

This guide covers all the ways to run the Paradise Automator bot.

---

## Quick Reference

| Scenario | Script | Command |
|----------|--------|---------|
| VPS via RDP Desktop | `run.sh` | `./run.sh` |
| VPS via SSH (headless) | `run-headless.sh` | `./run-headless.sh` |
| Local testing (Mac) | `run.sh` | `./run.sh` |
| Test mode (runs every 5 min) | Either | `./run.sh --test` |
| Run daily report immediately | Either | `./run.sh --run-now` |
| Run weekly report immediately | Either | `./run.sh --run-weekly` |

---

## Prerequisites

### 1. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
nano .env  # or use your preferred editor
```

**Required for auto-login:**
```
REI_USERNAME=your-email@example.com
REI_PASSWORD=your-password-here
```

Without these, you'll need to manually log in via a visible browser window.

### 2. Dependencies (VPS already has these)

```bash
# Python packages
pip install playwright python-dotenv schedule requests

# Playwright browsers
playwright install chromium

# For headless mode (Linux only)
sudo apt install xvfb
```

---

## Option 1: VPS via SSH (Headless) — Recommended for Production

This is the best way to run permanently on your VPS.

### Step 1: SSH into your VPS

```bash
ssh root@217.76.59.213
su - victor   # Switch to your user
cd ~/paradise-automator
```

### Step 2: Pull latest code

```bash
git pull
```

### Step 3: Start in a Screen Session (so it survives disconnect)

```bash
# Create a named screen session
screen -S bot

# Run the bot in headless mode
./run-headless.sh

# Wait for "AUTOMATION IS LIVE" message
# Then detach: Press Ctrl+A, then D
```

You can now close your terminal or sleep your laptop. The bot keeps running!

### Step 4: Reconnect later to check on it

```bash
ssh root@217.76.59.213
su - victor
screen -r bot   # Reattach to see the bot
```

---

## Option 2: VPS via RDP Desktop (Headed)

Use this for first-time setup, debugging, or when you need to see the browser.

### Step 1: Connect to VPS Desktop

Use Microsoft Remote Desktop or another RDP client to connect to `217.76.59.213`.

### Step 2: Open Terminal and Run

```bash
cd ~/paradise-automator
./run.sh
```

Or double-click the **"Run Paradise Bot"** desktop shortcut.

### Step 3: Log in (if needed)

If REI credentials aren't in `.env`, you'll need to manually log in to REI Cloud in the browser window, then press ENTER in the terminal.

---

## Option 3: Local Testing (Mac/Linux)

For testing changes before deploying to VPS.

### Step 1: Setup (first time only)

```bash
cd ~/Documents/paradise-automator
python3 -m venv venv
source venv/bin/activate
pip install playwright python-dotenv schedule requests
playwright install chromium
```

### Step 2: Create/update .env

Make sure `.env` has your credentials:
```
REI_USERNAME=your-email@example.com
REI_PASSWORD=your-password-here
```

### Step 3: Run

```bash
source venv/bin/activate
./run.sh
```

A browser window will open and auto-login.

### Step 4: Test mode (optional)

For faster testing (runs report every 5 minutes instead of daily):

```bash
./run.sh --test
```

---

## Screen Command Reference

Screen lets processes run independently of your SSH connection.

| Command | What it does |
|---------|--------------|
| `screen -S bot` | Create a new session named "bot" |
| `Ctrl+A, D` | Detach from session (keeps it running) |
| `screen -r bot` | Reattach to the "bot" session |
| `screen -ls` | List all running screen sessions |
| `screen -d -r bot` | Force detach and reattach (if left attached elsewhere) |
| `exit` | Kill the session (run from inside screen) |

### Common Scenarios

**"Screen is already attached"** — you're connected from another terminal:
```bash
screen -d -r bot   # Force detach and reattach here
```

**List all screens:**
```bash
screen -ls
# Output:
#   12345.bot   (Detached)
#   12346.other (Attached)
```

**Kill a stuck screen:**
```bash
screen -X -S bot quit
```

---

## Command Line Options

```bash
./run.sh [OPTIONS]
./run-headless.sh [OPTIONS]
```

| Option | Description |
|--------|-------------|
| (none) | Production mode - daily at 06:01, weekly on Saturdays at 10:00 |
| `--test` | Test mode - runs report every 5 minutes |
| `--run-now` | Run daily report immediately, then continue with schedule |
| `--run-weekly` | Run weekly report immediately, then continue with schedule |
| `--record` | Development mode - record workflow URLs |

### Schedules

| Report | Schedule | Email Content |
|--------|----------|---------------|
| Daily | 06:01 every day | Tomorrow's arrivals/departures |
| Weekly | 10:00 every Saturday | Next 7 days, day-by-day summary for cleaning company planning |

### Manual Triggers (while bot is running)

Type these commands while the bot is running to manually trigger reports:

| Command | Action |
|---------|--------|
| `run_d` | Trigger daily report immediately |
| `run_w` | Trigger weekly report immediately |

### Examples

```bash
# Production mode (daily at 06:01, weekly Saturdays at 10:00)
./run-headless.sh

# Run daily report immediately, then continue schedule
./run-headless.sh --run-now

# Run weekly report immediately, then continue schedule
./run-headless.sh --run-weekly

# Test mode (every 5 minutes)
./run-headless.sh --test
```

---

## Troubleshooting

### Bot died in screen

```bash
screen -r bot
# If it crashed, you'll see the error. Restart with:
./run-headless.sh
```

### "No display" or "X server" error

You're trying to run headed mode without a display. Use headless:
```bash
./run-headless.sh
```

### Session keeps expiring

The heartbeat runs every 30 minutes. If it still expires:
1. Check that auto re-login is working (credentials in `.env`)
2. Check the logs: `tail -100 automation.log`

### Missing module errors

```bash
source venv/bin/activate
pip install playwright python-dotenv schedule requests
```

---

## Logs

View recent logs:
```bash
tail -100 automation.log
```

Watch logs live:
```bash
tail -f automation.log
```

---

## Summary: The Simplest Production Setup

```bash
# SSH in
ssh root@217.76.59.213
su - victor
cd ~/paradise-automator

# Update code
git pull

# Start in screen
screen -S bot
./run-headless.sh

# Detach (Ctrl+A, D)
# Done! Close terminal, the bot keeps running.
```
