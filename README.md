# Claude Usage Bar for Windows

> [日本語はこちら](#claude-usage-bar-for-windows-日本語)

Windows system tray application that monitors your Claude Pro/Team and ChatGPT Codex usage in real-time.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Windows](https://img.shields.io/badge/platform-Windows-0078d4)
![License](https://img.shields.io/badge/license-BSD--2--Clause-green)

## Features

- **Dual Provider Support** — Monitor both Claude and ChatGPT Codex usage side by side
- **Primary / Secondary Display** — Choose which provider gets the full view (with chart); the other is shown in compact mode
- **System Tray Icon** — Displays your current usage percentage directly in the taskbar, color-coded by severity (green → yellow → orange → red)
- **Frameless Popup Window** — Clean, modern dark UI appears at the bottom-right corner of the screen
- **Usage Tracking** — Monitors 5-hour and 7-day usage windows, with per-model breakdown (Opus / Sonnet) for Claude
- **Extra Usage** — Tracks paid add-on credit consumption (Claude)
- **Historical Chart** — Visualizes usage trends over 1h / 6h / 1d / 7d / 30d (primary provider)
- **Notifications** — Windows toast alerts when usage crosses configurable thresholds
- **Auto-Polling** — Configurable polling interval (5m / 15m / 30m / 1h)
- **Launch at Login** — Optional Windows startup registration

## Installation

### From Release (recommended)

Download `ClaudeUsageBarModern.exe` from [Releases](https://github.com/character-s/claude-usage-bar-windows/releases) and run it. No installation required.

### From Source

```bash
git clone https://github.com/character-s/claude-usage-bar-windows.git
cd claude-usage-bar-windows

pip install -r requirements.txt
pip install bottle pywebview
# Python 3.13+ requires pre-release pythonnet:
pip install pythonnet --pre

python main_modern.py
```

#### Dependencies

| Package | Purpose |
|---------|---------|
| pystray | System tray icon |
| Pillow | Tray icon rendering |
| requests | Anthropic & ChatGPT API calls |
| winotify | Windows toast notifications |
| bottle | Local REST API server |
| pywebview | Frameless webview window |
| pythonnet | WebView2 backend (EdgeChromium) |

## Usage

1. Launch the app — a tray icon appears in the taskbar
2. Click the tray icon to open the popup window
3. Click **Sign in with Claude** and complete the OAuth flow
4. Your usage data will be displayed and auto-refreshed

### Adding ChatGPT Codex

1. Open **Settings** → scroll to **Codex Account**
2. Click the link to open `chatgpt.com/api/auth/session` in your browser
3. Sign in to ChatGPT if needed — the page will display session JSON
4. Select all and copy the entire page content (Ctrl+A → Ctrl+C)
5. Paste it into the input field in the app and click **Submit Token**
6. The app automatically extracts the `accessToken` from the JSON

> **Note:** ChatGPT session tokens expire periodically. When the token expires, the app will prompt you to sign in again.

### Primary Display

In **Settings → Primary Display**, choose which provider to show in full view:

- **Claude** (default) — Full-size bars + historical chart; Codex shown compact below
- **Codex** — Full-size bars; Claude shown compact below (no chart for Codex)

### Tray Icon

- **Left click** — Toggle popup window
- **Right click** — Context menu (display mode, refresh, quit)
- The icon shows your current usage percentage with color coding

### Settings

Access via the **Settings** link in the popup:

- **Polling Interval** — How often to check usage (5m / 15m / 30m / 1h)
- **Primary Display** — Choose which provider to prioritize (Claude / Codex)
- **Notification Thresholds** — Alert when 5h, 7d, or extra usage exceeds a percentage
- **Launch at Login** — Start automatically with Windows
- **Claude Account** — Sign out of Claude
- **Codex Account** — Sign in / sign out of ChatGPT Codex

## Building

```bash
pip install pyinstaller
python -m PyInstaller build_modern.spec --noconfirm
```

Output: `dist/ClaudeUsageBarModern.exe`

## Architecture

```
main_modern.py          Entry point
├── usage_service.py    Claude OAuth + API polling
├── codex_service.py    ChatGPT Codex session auth + API polling
├── history_service.py  Usage history persistence
├── notification_service.py  Windows toast alerts
├── credentials_store.py     Claude token storage
├── tray_icon.py        Dynamic tray icon rendering
├── ui_modern.py        Bottle API server + pywebview window
└── web/
    ├── index.html      UI markup
    ├── style.css       Windows 11 dark theme
    ├── app.js          Frontend logic
    └── chart.min.js    Chart.js (bundled)
```

**Threading model:**
- Main thread: pywebview (requires COM initialization)
- Background thread: pystray (system tray)
- Background thread: Bottle REST server
- Background threads: Usage polling (Claude + Codex)

## Data Storage

All data is stored locally at `~/.config/claude-usage-bar/`:

| File | Contents |
|------|----------|
| `credentials.json` | Claude OAuth tokens |
| `codex_credentials.json` | ChatGPT Codex access token |
| `history.json` | Usage history (30-day retention) |
| `settings.json` | Polling interval, thresholds, primary provider, preferences |

## Credits

This project is a Windows port inspired by [claude-usage-bar](https://github.com/Blimp-Labs/claude-usage-bar) by [Krystian (Blimp Labs)](https://github.com/Blimp-Labs) — the original macOS menu bar app for tracking Claude usage. The UI design and core concept originate from that project. Built from scratch in Python for Windows, as the original is macOS-only (Swift).

ChatGPT Codex usage API integration is based on insights from [AgentLimits](https://github.com/Nihondo/AgentLimits).

## License

BSD 2-Clause License. See [LICENSE](LICENSE) for details.

---

# Claude Usage Bar for Windows (日本語)

Claude Pro/Team と ChatGPT Codex の使用量をリアルタイムで監視する Windows システムトレイアプリケーションです。

## 機能

- **デュアルプロバイダー対応** — Claude と ChatGPT Codex の使用量を並べて表示
- **優先表示切替** — 選んだプロバイダーをフル表示（チャート付き）、もう一方はコンパクト表示
- **システムトレイアイコン** — 現在の使用率をタスクバーに直接表示。色分けで一目瞭然（緑 → 黄 → 橙 → 赤）
- **フレームレスポップアップ** — 画面右下に表示されるモダンなダークUI
- **使用量トラッキング** — 5時間・7日間の使用枠を監視。Claudeはモデル別内訳（Opus / Sonnet）対応
- **Extra Usage** — 有料追加クレジットの消費量を追跡（Claude）
- **履歴チャート** — 1時間 / 6時間 / 1日 / 7日 / 30日の使用推移を可視化（優先プロバイダー）
- **通知** — 設定した閾値を超えるとWindowsトースト通知でアラート
- **自動ポーリング** — 取得間隔を設定可能（5分 / 15分 / 30分 / 1時間）
- **スタートアップ登録** — Windows起動時に自動でサイレント起動

## インストール

### リリースから（推奨）

[Releases](https://github.com/character-s/claude-usage-bar-windows/releases) から `ClaudeUsageBarModern.exe` をダウンロードして実行するだけです。インストール不要。

### ソースから

```bash
git clone https://github.com/character-s/claude-usage-bar-windows.git
cd claude-usage-bar-windows

pip install -r requirements.txt
pip install bottle pywebview
# Python 3.13以降はpythonnetのプレリリース版が必要:
pip install pythonnet --pre

python main_modern.py
```

#### 依存パッケージ

| パッケージ | 用途 |
|-----------|------|
| pystray | システムトレイアイコン |
| Pillow | トレイアイコン描画 |
| requests | Anthropic & ChatGPT API通信 |
| winotify | Windowsトースト通知 |
| bottle | ローカルRESTサーバー |
| pywebview | フレームレスWebViewウィンドウ |
| pythonnet | WebView2バックエンド（EdgeChromium） |

## 使い方

1. アプリを起動するとタスクバーにトレイアイコンが表示されます
2. トレイアイコンをクリックしてポップアップウィンドウを開きます
3. **Sign in with Claude** をクリックしてOAuth認証を完了します
4. 使用量データが表示され、自動更新されます

### ChatGPT Codex の追加

1. **Settings** を開き、**Codex Account** セクションまでスクロール
2. リンクをクリックしてブラウザで `chatgpt.com/api/auth/session` を開く
3. 必要に応じてChatGPTにログイン — ページにセッションJSONが表示される
4. ページ全体を選択してコピー（Ctrl+A → Ctrl+C）
5. アプリの入力欄に貼り付けて **Submit Token** をクリック
6. JSONから `accessToken` が自動抽出されます

> **注意:** ChatGPTのセッショントークンは定期的に失効��ます。失効時はアプリが再サインインを促します。

### 優先表示の切替

**Settings → Primary Display** で優先プロバイダーを選択:

- **Claude**（デフォルト） — フルサイズバー＋履歴チャート表示。Codexはコンパクト表示
- **Codex** — フルサイズバー表示。Claudeはコンパクト表示（Codexにはチャートなし）

### トレイアイコン

- **左クリック** — ポップアップの表示/非表示
- **右クリック** — コンテキストメニュー（表示モード、ウィジェットモード、更新、終了）
- アイコンには現在の使用率が色付きで表示されます

### 設定

ポップアップ内の **Settings** リンクからアクセス:

- **ポーリング間隔** — 使用量の取得頻度（5分 / 15分 / 30分 / 1時間）
- **優先表示** — 優先プロバイダーの選択（Claude / Codex）
- **通知閾値** — 5時間枠・7日間枠・Extra使用量がしきい値を超えた時にアラート
- **スタートアップ登録** — Windows起動時に自動起動（サイレントモード）
- **Claude Account** — Claudeからサインアウト
- **Codex Account** — ChatGPT Codex のサインイン / サインアウト

## ビルド

```bash
pip install pyinstaller
python -m PyInstaller build_modern.spec --noconfirm
```

出力: `dist/ClaudeUsageBarModern.exe`

## アーキテクチャ

```
main_modern.py          エントリポイント
├── usage_service.py    Claude OAuth認証 + APIポーリング
├── codex_service.py    ChatGPT Codex セッション認証 + APIポーリング
├── history_service.py  使用履歴の永続化
├── notification_service.py  Windowsトースト通知
├── credentials_store.py     Claudeトークン保存
├── tray_icon.py        動的トレイアイコン描画
├── ui_modern.py        Bottle APIサーバー + pywebviewウィンドウ
└── web/
    ├── index.html      UIマークアップ
    ├── style.css       Windows 11ダークテーマ
    ├── app.js          フロントエンドロジック
    └── chart.min.js    Chart.js（バンドル済み）
```

**スレッドモデル:**
- メインスレッド: pywebview（COM初期化が必要）
- バックグラウンド: pystray（システムトレイ）
- バックグラウンド: Bottle RESTサーバー
- バックグラウンド: 使用量ポーリング（Claude + Codex）

## データ保存先

全データは `~/.config/claude-usage-bar/` にローカル保存:

| ファイル | 内容 |
|---------|------|
| `credentials.json` | Claude OAuthトークン |
| `codex_credentials.json` | ChatGPT Codex アクセストークン |
| `history.json` | 使用履歴（30日間保持） |
| `settings.json` | ポーリング間隔、通知閾値、優先プロバイダー、設定 |

## クレジット

本プロジェクトは [claude-usage-bar](https://github.com/Blimp-Labs/claude-usage-bar)（[Krystian (Blimp Labs)](https://github.com/Blimp-Labs) 作）にインスパイアされた Windows 移植版です。UIデザインとコンセプトは元プロジェクトに由来します。macOS専用（Swift）の元版をWindowsで使うため、Pythonで新規開発しました。

ChatGPT Codex 使用量API連携は [AgentLimits](https://github.com/Nihondo/AgentLimits) の実装を参考にしています。

## ライセンス

BSD 2-Clause License。詳細は [LICENSE](LICENSE) を参照。
