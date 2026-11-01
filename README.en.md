# desk-presence MCP

> **The Ultimate Physical CAPTCHA for AI Agents**  
> **Eject the DVD tray. Require a human to push it closed. Verify true physical presence.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://www.microsoft.com/)
[![MCP Spec](https://img.shields.io/badge/MCP-1.x%20%2F%202.x-green.svg)](https://modelcontextprotocol.io/)

[日本語版 README はこちら (README.md)](./README.md)

---

## 💡 Concept

When autonomous AI agents pair-program or execute automated workflows, there are critical moments—such as before executing destructive commands, running high-cost API tasks, or making irreversible architectural decisions—where you need absolute certainty: **Is a human actually sitting in front of the machine right now?**

Screen popups, browser notifications, chime sounds, and keypresses can be intercepted or forged by software automation. 

**Pushing a physically ejected motorized DVD tray back into the computer case cannot be forged.** It requires a physical human body within arm's reach of the desktop.

`desk-presence` transforms your dusty optical drive into a **physical cyber-physical doorbell and presence sensor** via the standard Model Context Protocol (MCP).

```
[ AI Agent ] 
     │  "Important decision pending. Are you at your desk?"
     │  (calls presence_check tool)
     ▼
[ Optical Drive ] ──▶ *Whirrr... Clack* (Tray physically opens)
     ▲
     │  *Snap* (Human manually pushes the tray closed)
     │
[ desk-presence ] ──▶ Sensed via low-level SCSI TEST UNIT READY!
     │
     ▼
[ AI Agent ] ──▶ "Physical human confirmed. Resuming execution."
```

---

## 🛠 Deep Win32 Architecture

Behind the comical concept lies an uncompromisingly serious low-level Win32 implementation:

1. **Direct SCSI Pass-Through Control**
   * Rather than relying solely on high-level Windows shell APIs, the server uses `IOCTL_SCSI_PASS_THROUGH` to dispatch raw SCSI Command Descriptor Blocks (`CDB 00h: TEST UNIT READY`) directly to the optical drive hardware.
   * Real-time SCSI Sense Key / ASC / ASCQ decoding:
     * `ASC 3Ah / ASCQ 02h`: `MEDIUM NOT PRESENT - TRAY OPEN` (Fully open)
     * `ASC 3Ah / ASCQ 01h`: `MEDIUM NOT PRESENT - TRAY CLOSED` (Fully closed)
     * `ASC 04h`: `LOGICAL UNIT NOT READY` (Mechanism in motion)
2. **Premature Closure Detection**
   * If a human reflexively slaps the tray closed before it finishes fully extending, the state machine detects and reports this edge case (`closed_before_open_confirmed`).
3. **Dual MCP SDK Compatibility**
   * Automatically adapts to either MCP 1.x (`mcp.server.fastmcp`) or MCP 2.x (`mcp.server.mcpserver`).
4. **Stdio & Streamable HTTP Transports**
   * Supports `stdio` for local AI clients (Claude Desktop, Antigravity, Cursor, Windsurf) and `Streamable HTTP` for remote network setups.

---

## 📦 Requirements

* **OS:** Windows 10 / 11
* **Hardware:** Any motorized tray-loading optical drive (CD/DVD/Blu-ray, internal SATA or USB external)
* **Python:** 3.10+
* **Dependencies:**
  ```bash
  pip install -r requirements.txt
  ```

---

## 🚀 Installation & Setup

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/your-username/desk-presence-mcp.git
cd desk-presence-mcp
pip install -r requirements.txt
```

### 2. Configure Your AI Client

#### Claude Desktop (`claude_desktop_config.json`)
Add to `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "desk-presence": {
      "command": "python",
      "args": ["C:\\path\\to\\desk_presence_server.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

#### Antigravity / Gemini CLI (`mcp_config.json`)
Add to `~/.gemini/config/mcp_config.json`:
```json
{
  "mcpServers": {
    "desk-presence": {
      "command": "python",
      "args": ["C:\\path\\to\\desk_presence_server.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

#### Cursor / Windsurf
In your IDE's MCP Settings, add a new server with command `python`, pass the absolute path to `desk_presence_server.py` as an argument, and set environment variable `MCP_TRANSPORT=stdio`.

---

## 📖 Available Tools

### `presence_check`
Opens the optical drive tray and waits until a human pushes it closed. Returns `present: true` immediately when closure is confirmed.

* **Parameters:**
  * `timeout_sec` (int, 5–300, default: 60): Maximum seconds to wait. If timed out, the tray automatically closes as cleanup and returns `present: false`.
  * `debug` (bool, default: false): Includes millisecond-by-millisecond state polling trace.
* **Sample Response:**
  ```json
  {
    "present": true,
    "response_sec": 10.5,
    "response_since_command_sec": 13.8,
    "eject_sec": 3.0,
    "evidence": "closed_state"
  }
  ```

### `drive_status`
Queries the drive's current hardware state (open, closed_empty, closed_disc, or busy) for debugging.

---

## 🤖 Recommended Agent Instructions

Add this to your project's agent rules (e.g., `.cursorrules`, `GEMINI.md`, or Claude Custom Instructions):

```markdown
When you need to align on critical decisions, perform destructive actions, or verify that the user is physically present at their desk, use the desk-presence MCP `presence_check` tool.
The DVD tray will open and wait for the human to manually push it closed (present=true). Only present your question or continue after presence is confirmed.
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `MCP_TRANSPORT` | `streamable-http` | Transport mode: `stdio` or `streamable-http`. |
| `MCP_HOST` | `127.0.0.1` | Bind host for HTTP mode. |
| `MCP_PORT` | `8765` | Bind port for HTTP mode. |
| `DVD_DRIVE` | Auto-detect | Manually lock to a drive letter (e.g., `E:`). |
| `PRESENCE_FAST_DETECT` | `0` | Experimental: detect closure immediately upon drive busy state. |

---

## 📄 License

MIT License
