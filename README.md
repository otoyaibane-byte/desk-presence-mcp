# desk-presence MCP

> **AIエージェントのための究極の物理CAPTCHA**  
> **DVDドライブのトレイを開き、人間が手で閉じたことをもって「デスクに人間がいる」と判定するMCPサーバー**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://www.microsoft.com/)
[![MCP Spec](https://img.shields.io/badge/MCP-1.x%20%2F%202.x-green.svg)](https://modelcontextprotocol.io/)

[English README (README.en.md)](./README.en.md)

---

## 💡 コンセプト (What is this?)

AIエージェントとペアプロや自動化を行っているとき、**「重大な決定やファイル削除の前に、ユーザーが本当にPCの前にいるか確認したい」** という場面があります。

画面上のクリックや通知音、キー入力はマクロや別スクリプトでも自動応答できてしまいますが、**「物理的に飛び出したDVDトレイを手で押し戻す」という動作だけは、PCの前に実体として肉体が存在していなければ絶対に不可能です。**

`desk-presence` は、あなたのPCの光学ドライブを**AIと現実世界をつなぐ物理呼び鈴（アナログ在席センサー）**に変えるMCP（Model Context Protocol）サーバーです。

```
[ AI Agent ] 
     │  "重要な確認があります。席にいますか？"
     │  (presence_check ツールを実行)
     ▼
[ DVD Drive ] ──▶ ウィーン…（トレイが勝手に全開になる）
     ▲
     │  ペチッ（人間が手でトレイを押し戻す）
     │
[ desk-presence ] ──▶ SCSI TEST UNIT READY で閉鎖を即時検知！
     │
     ▼
[ AI Agent ] ──▶ "肉体存在を確認。本題に入ります。"
```

---

## 🛠 技術的特徴 (Deep Win32 Architecture)

お遊びツールに見えて、内部実装は**Win32低レイヤーの職人芸**で組まれています：

1. **SCSI Pass-Through によるダイレクト制御**
   * 単にOSの開閉APIを叩くだけでなく、`IOCTL_SCSI_PASS_THROUGH` を通じてドライブへ直接 `TEST UNIT READY` (CDB `00h`) を発行。
   * 返ってきたSenseデータの ASC/ASCQ をリアルタイム解析：
     * `ASC 3Ah / ASCQ 02h`: MEDIUM NOT PRESENT - TRAY OPEN（トレイ全開）
     * `ASC 3Ah / ASCQ 01h`: MEDIUM NOT PRESENT - TRAY CLOSED（トレイ閉鎖）
     * `ASC 04h`: LOGICAL UNIT NOT READY（開閉動作中）
2. **「早閉じ（反射的な押し戻し）」の検知**
   * トレイが開き切る前に人間が反射的にパタンと閉じてしまった場合（`closed_before_open_confirmed`）も考慮されたステートマシン。
3. **MCP 1.x (FastMCP) & 2.x (MCPServer) 両対応**
   * ライブラリ環境に合わせて自動フォールバック。
4. **Stdio & Streamable HTTP 両対応**
   * デスクトップクライアント（Claude Desktop, Antigravity, Cursor等）には高速な `stdio`、リモート接続には `Streamable HTTP` を選択可能。

---

## 📦 必要要件 (Requirements)

* **OS:** Windows 10 / 11
* **ハードウェア:** トレイ開閉式の光学ドライブ（CD/DVD/BD内蔵ドライブ または USB外付けドライブ）
* **Python:** 3.10 以上
* **ライブラリ:**
  ```bash
  pip install -r requirements.txt
  ```

---

## 🚀 インストール & 設定 (Setup)

### 1. リポジトリのクローン & 依存インストール
```bash
git clone https://github.com/your-username/desk-presence-mcp.git
cd desk-presence-mcp
pip install -r requirements.txt
```

### 2. 各AIエージェントへの登録

#### Antigravity / Gemini CLI (`mcp_config.json`)
`~/.gemini/config/mcp_config.json` に追加：
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

#### Claude Desktop (`claude_desktop_config.json`)
`%APPDATA%\Claude\claude_desktop_config.json` に追加：
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
MCP設定画面から Command に `python`、Args にスクリプトのフルパスを指定し、環境変数に `MCP_TRANSPORT=stdio` を追加してください。

---

## 📖 提供ツール (Available Tools)

### `presence_check`
DVDトレイを開き、人間が閉じるのを待機します。手で閉じられた時点で在席確定（`present: true`）を返します。

* **引数:**
  * `timeout_sec` (int, 5〜300秒, デフォルト: 60): トレイが閉じられるのを待つ制限時間。タイムアウト時は不在として自動でトレイを閉じます。
  * `debug` (bool, デフォルト: false): ポーリング毎の詳細な時間・ステートログを含めます。
* **返り値:**
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
光学ドライブの現在のトレイ開閉状態を取得します（デバッグ・事前確認用）。

---

## 🤖 エージェント向けプロンプト・ルール設定例

AIエージェント（`.cursorrules`, `GEMINI.md`, Claude Custom Instructions等）に以下のように指示しておくと効果的です：

```markdown
ユーザーとの重要な認識のすり合わせや破壊的コマンドの実行前、あるいはユーザーが席にいるか確認したいときは、desk-presence MCP の `presence_check` ツールを使用してください。
DVDドライブのトレイが開き、ユーザーが手で閉じることで在席（present=true）が確認されます。在席を確認してから本題の質問を提示してください。
```

---

## ⚙️ 環境変数オプション (Environment Variables)

| 変数名 | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `MCP_TRANSPORT` | `streamable-http` | `stdio` または `streamable-http` を指定。 |
| `MCP_HOST` | `127.0.0.1` | HTTPモード時のリッスンホスト。 |
| `MCP_PORT` | `8765` | HTTPモード時のリッスンポート。 |
| `DVD_DRIVE` | 自動検出 | ドライブ文字を固定したい場合に指定（例: `E:`）。 |
| `PRESENCE_FAST_DETECT` | `0` | ドライブのBUSY応答による即時検知を有効化（試験的）。 |

---

## 📄 ライセンス (License)

MIT License
