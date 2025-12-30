# Scheduling the Automation

Run the REI Cloud automation daily at a specific time.

## Mac (using cron)

### 1. Open crontab editor

```bash
crontab -e
```

### 2. Add the schedule

Run at 8:00 AM daily:

```cron
0 8 * * * cd /Users/victor/Documents/paradise-automator && /usr/bin/python3 rei_cloud_automation.py >> automation.log 2>&1
```

**Cron format**: `minute hour day month weekday`

Examples:
- `0 8 * * *` = 8:00 AM every day
- `0 7 * * 1-5` = 7:00 AM weekdays only
- `30 6 * * *` = 6:30 AM every day

### 3. Verify

```bash
crontab -l
```

---

## Mac (using launchd - recommended)

More reliable than cron on macOS.

### 1. Create the plist file

```bash
nano ~/Library/LaunchAgents/com.paradise.reicloud.plist
```

### 2. Add this content

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.paradise.reicloud</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/victor/Documents/paradise-automator/rei_cloud_automation.py</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>/Users/victor/Documents/paradise-automator</string>
    
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    
    <key>StandardOutPath</key>
    <string>/Users/victor/Documents/paradise-automator/automation.log</string>
    
    <key>StandardErrorPath</key>
    <string>/Users/victor/Documents/paradise-automator/automation.log</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

### 3. Load the schedule

```bash
launchctl load ~/Library/LaunchAgents/com.paradise.reicloud.plist
```

### 4. Verify

```bash
launchctl list | grep reicloud
```

### 5. Unload if needed

```bash
launchctl unload ~/Library/LaunchAgents/com.paradise.reicloud.plist
```

---

## Linux (using cron)

```bash
crontab -e
```

Add:

```cron
0 8 * * * cd /home/ubuntu/paradise-automator && /usr/bin/python3 rei_cloud_automation.py >> automation.log 2>&1
```

---

## Windows (Task Scheduler)

1. Open **Task Scheduler** (search in Start menu)
2. Click **Create Basic Task**
3. Name: "REI Cloud Automation"
4. Trigger: **Daily** at 8:00 AM
5. Action: **Start a program**
   - Program: `python`
   - Arguments: `rei_cloud_automation.py`
   - Start in: `C:\path\to\paradise-automator`
6. Finish and enable the task

---

## Testing Your Schedule

### Run manually first

```bash
cd /Users/victor/Documents/paradise-automator
python rei_cloud_automation.py
```

### Check logs

```bash
tail -f automation.log
```

### Test the scheduled job immediately (Mac launchd)

```bash
launchctl start com.paradise.reicloud
```
