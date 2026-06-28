# VYREN — iPhone Access Setup Guide

## Quick Start (Laptop Must Be On)

### Step 1: Start VYREN Server
```bash
cd vyren
python server.py
```
You'll see: `Dashboard: http://localhost:8420`

### Step 2: Expose to the Internet

**Option A: ngrok (Fastest — 30 seconds)**
```bash
# Install ngrok from https://ngrok.com/download
ngrok http 8420
```
ngrok gives you a URL like `https://abc123.ngrok-free.app`
Open that URL on your iPhone.

**Option B: Cloudflare Tunnel (Free, Permanent)**
```bash
# Install cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel --url http://localhost:8420
```
Gives you a `trycloudflare.com` URL. Same deal — open on iPhone.

**Option C: Tailscale (Best if both devices have Tailscale)**
```bash
# Install Tailscale on both laptop and iPhone
# Then access: http://<your-laptop-tailscale-ip>:8420
```

### Step 3: Add VYREN to iPhone Home Screen
1. Open the URL in **Safari** (not Chrome)
2. Tap the **Share** button (box with arrow)
3. Tap **"Add to Home Screen"**
4. Name it "VYREN", tap Add

Now it appears as an app icon. Tapping it opens VYREN fullscreen — no browser bars. The mic button uses iPhone's built-in speech recognition (no API key needed).

---

## "Even If My Laptop Is Off" — Cloud Deployment

To use VYREN when your laptop is off, you need VYREN running on a server that's always on.

### Option 1: Railway.app (Easiest — Free Tier Available)
1. Push VYREN to a GitHub repo
2. Go to https://railway.app, sign in with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Railway auto-detects Python, installs requirements
5. Set environment variables: `GEMINI_API_KEY`
6. Railway gives you a public URL
7. Open on iPhone, add to home screen

### Option 2: Render.com (Free Tier)
1. Push to GitHub
2. Go to https://render.com → New Web Service
3. Connect repo, set:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Add env var: `GEMINI_API_KEY`
5. Get your URL, open on iPhone

### Option 3: Your Own VPS (DigitalOcean/Hetzner — ~$4/month)
```bash
# On the VPS:
git clone your-repo
cd vyren
pip install -r requirements.txt
export GEMINI_API_KEY=your-key-here

# Run with a process manager:
npm install -g pm2  # or use systemd
pm2 start server.py --interpreter python3 --name vyren
pm2 save
pm2 startup  # auto-start on reboot

# Or use systemd (no Node needed):
sudo cp vyren.service /etc/systemd/system/
sudo systemctl enable vyren
sudo systemctl start vyren
```

### Option 4: Raspberry Pi at Home (Always-on, ~$5 electricity/month)
Same as VPS but runs on a Raspberry Pi on your desk. Use Cloudflare Tunnel to expose it.

---

## iPhone Features

| Feature | How |
|---------|-----|
| Chat | Text input at bottom |
| Voice | Tap mic button (uses iPhone Speech Recognition) |
| System Monitor | Monitor tab (auto-refreshes every 5s) |
| Memory | Memory tab — see everything VYREN remembers |
| Tools | Tools tab — see all capabilities |
| Kill Switch | Settings tab |
| Offline caching | Service worker caches the dashboard UI |

## Security Notes

- The WebSocket uses the same protocol (ws:// or wss://) as your tunnel
- ngrok and Cloudflare both provide HTTPS automatically
- For production, always use HTTPS (wss://)
- Keep your GEMINI_API_KEY secret — never commit it to git
- The kill switch is available in Settings if you need to pause VYREN remotely