# VPS Migration Guide

Run your automation 24/7 on a remote server. You can "remote in" to authenticate, then disconnect and leave it running.

## Option A: Windows VPS (Easiest)
**Best for**: Users who want a familiar desktop environment. You can RDP in, open the window, log in, and disconnect.

1.  **Rent a Windows VPS**
    *   Providers: Vultr, OVH, AWS Lightsail (Windows Server).
    *   Specs: 2GB RAM minimum (4GB recommended for browser automation).
    *   Cost: ~$10-20/mo.

2.  **Connect via RDP**
    *   On Mac: Use "Microsoft Remote Desktop" app.
    *   Connect to the IP address with the Administrator credentials provided by your host.

3.  **Setup Environment**
    *   Install **Python**: Download installer from python.org. Check "Add Python to PATH".
    *   Open PowerShell/Command Prompt.
    *   Install dependencies:
        ```powershell
        pip install playwright schedule python-dotenv
        playwright install
        ```

4.  **Transfer Script**
    *   Copy your `rei_cloud_automation.py` file to the VPS (e.g., paste it into Notepad).
    *   Create a folder `C:\Automation`.

5.  **Run It**
    *   Open PowerShell in the folder.
    *   Run: `python rei_cloud_automation.py --run-now`
    *   The browser will open. **Log in manually**.
    *   Press ENTER in the terminal to start the loop.

6.  **Disconnect**
    *   **CRITICAL**: Do NOT click "Sign Out".
    *   Simply close the RDP window (click the X).
    *   The session stays active, browser stays open, script keeps running.

---

## Option B: Linux VPS (Cheaper)
**Best for**: Cost savings ($5/mo). Requires setting up a desktop environment.

1.  **Rent a Linux VPS**
    *   Providers: DigitalOcean, Vultr, Linode.
    *   OS: Ubuntu 22.04 or 24.04.

2.  **Install Desktop & Remote Access (XRDP)**
    *   SSH into the server.
    *   Install XFCE (lightweight desktop) and XRDP:
        ```bash
        sudo apt update
        sudo apt install xfce4 xfce4-goodies xorg dbus-x11 x11-xserver-utils
        sudo apt install xrdp
        sudo systemctl enable xrdp
        sudo systemctl start xrdp
        ```

3.  **Connect via RDP**
    *   Use "Microsoft Remote Desktop" on Mac.
    *   Connect to the VPS IP. You will see a Linux desktop.

4.  **Setup Python & Script**
    *   Open the Terminal in the Linux desktop.
    *   Install:
        ```bash
        sudo apt install python3-pip
        pip3 install playwright schedule python-dotenv
        playwright install
        playwright install-deps
        ```

5.  **Run It**
    *   Transfer your script (git clone or copy-paste).
    *   Run: `python3 rei_cloud_automation.py --run-now`
    *   Browser opens. Log in. Press Enter.

6.  **Disconnect**
    *   Just close the RDP window. The session keeps running.

## Moving Files to VPS
You can use `scp` to copy your current script to the remote server:

```bash
# For Linux
scp rei_cloud_automation.py root@YOUR_VPS_IP:/root/

# For Windows (if using SSH) or just copy/paste via RDP clipboard.
```
