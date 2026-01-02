# Deployment Guide: Desktop VPS (GUI Access)

This guide explains how to run the automation on a VPS that has a **Usage Desktop (GUI)**. This allows you to:
1.  Connect to the server using **Microsoft Remote Desktop** (from your Mac).
2.  See the actual browser window.
3.  Log in manually (solving 2FA/Captchas easily).
4.  Watch the bot run in real-time.

This is the most reliable method because it mimics your local Mac setup exactly.

## Option 1: Windows VPS (Easiest, Slightly more expensive)
A Windows VPS works exactly like a remote Windows PC.
*   **Provider**: Hetzner (Cloud), Contabo, or OVH.
*   **Cost**: ~$10-20 USD/month (includes license).
*   **Setup**:
    1.  Buy a Windows Server VPS (e.g. Windows Server 2022).
    2.  Download **Microsoft Remote Desktop** from the Mac App Store.
    3.  Connect using the IP and Administrator password.
    4.  Install Python and Git (standard Windows installers).
    5.  Clone this repo and run `run.sh` (or `python rei_cloud_automation.py`).

## Option 2: Linux VPS + Desktop Interface (Cheapest, Recommended)
You can install a lightweight desktop environment on a cheap Linux server and connect to it like a remote desktop.

*   **Provider**: **Hetzner Cloud**.
    *   **Recommended Models** (select "Shared vCPU" / "Cost Optimized"):
        *   **CX23** (Intel x86): ~€6/mo. **Most reliable/compatible choice.**
        *   **CAX11** (ARM64/Ampere): ~€4/mo. **Cheapest.**
    *   *Note: The "Shared vCPU" option is perfectly fine for this automation. You do NOT need Dedicated vCPU.*
    *   **OS**: Ubuntu 22.04 LTS (x86 for CX23, ARM64 for CAX11).

*   **Provider**: **DigitalOcean** (Alternative).
    *   **Recommended Droplet**: **Basic Regular** (Shared CPU).
    *   **Size**: 4GB RAM / 2 CPUs.
    *   **Cost**: ~$24/month.
    *   *Note: significantly more expensive than Hetzner for the same specs.*

### Step-by-Step Setup Guide

#### 1. Provision the Server
Create a generic Ubuntu 22.04 server on Hetzner/DigitalOcean. SSH into it once to set it up:
```bash
ssh root@<your-server-ip>
```

#### 2. Install Desktop & Remote Access (XRDP)
Run these commands to install a lightweight desktop (XFCE) and XRDP (Remote Desktop Protocol):

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install XFCE (Lightweight Desktop) and XRDP
sudo apt install -y xfce4 xfce4-goodies
sudo apt install -y xrdp filezilla firefox

# Configure XRDP to use XFCE
echo xfce4-session > ~/.xsession

# Restart XRDP
sudo systemctl restart xrdp
```

#### 3. Create a User (Security Best Practice)
Don't run the desktop as root.
```bash
# Create user 'victor' (or any name)
adduser victor
# (Follow prompts for password)

# Give admin rights
usermod -aG sudo victor

# Setup desktop for this user too
su - victor
echo xfce4-session > ~/.xsession
exit
```

#### 4. Connect from Mac
1.  Open **Microsoft Remote Desktop** (App Store).
2.  Add PC: `<your-server-ip>`.
3.  User account: `victor` and your password.
4.  Connect.
5.  You will see a Linux desktop! 🖥️

---

## Setting up the Bot (Inside the Remote Desktop)

Now that you are inside the GUI, open the **Terminal** (in the remote Linux desktop) and setup the bot just like you did on your Mac.

1.  **Clone Repo**:
    ```bash
    git clone https://github.com/your/repo.git paradise-automator
    cd paradise-automator
    ```
2.  **Install Python Deps**:
    ```bash
    sudo apt install -y python3-pip python3-venv
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    playwright install chromium
    playwright install-deps
    ```

3.  **Run**:
    ```bash
    ./run.sh
    ```

4.  **Login**:
    The browser will open on the screen. Log in manually. The script will remember your session!

## Keeping it Running 24/7
Since this is a desktop session, you have two choices:

1.  **Leave the session open**: Just disconnect RDP (don't log out). The programs usually keep running, but this can be fragile if the server reboots.
2.  **Use `tmux` or `screen`**: Run the script inside a terminal multiplexer so it survives checkouts.

### Recommended: Auto-Start on Reboot
Inside the remote desktop, search for "Session and Startup" in the applications menu.
Add a new Application Autostart:
*   Name: `Paradise Bot`
*   Command: `/bin/bash /home/victor/paradise-automator/run.sh`

Now, whenever the server reboots and you (or auto-login) starts the session, the bot runs.
