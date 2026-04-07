# Claude Usage Bar Windows - Project Guide

## Architecture
- pywebview (frameless=True) をメインスレッドで実行
- pystray をバックグラウンドスレッドで実行
- Bottle RESTサーバーをデーモンスレッドで実行
- pywebview は COM 初期化のためメインスレッドが必須（バックグラウンドだと「応答なし」になる）

## 技術的な注意事項

### フレームレスウィンドウ
- Edge --app モードでは Win32 API でタイトルバーを除去できない（Chrome が独自フレームを描画するため）
- pywebview + `frameless=True` を使うこと
- Python 3.14 では `pythonnet>=3.1.0rc0`（`pip install pythonnet --pre`）が必要。安定版は非対応

### ウィンドウリサイズ (DPI)
- pywebview の `resize()` は幅が変わる問題がある
- `SetWindowPos` を直接使い、`GetWindowRect` で現在の物理幅を保持して高さのみ変更する
- DPI は `GetDpiForWindow` で毎回取得する（事前キャッシュした `_dpi_scale` は初回リサイズ時に未設定の可能性）

## Codex デュアルプロバイダー機能
- Claude と ChatGPT Codex の使用量を1つのアプリで表示
- codex_service.py: chatgpt.com のセッション認証 + 使用量取得
- トークン保存先: `~/.config/claude-usage-bar/codex_credentials.json`
- ウィンドウ高さ: JS の `requestResize()` で scrollHeight 測定 → POST `/api/resize` → `SetWindowPos`

## Workflow Preferences
- 作業完了後はユーザーがcommit/pushを依頼するので、それまで勝手にcommitしない
- thinkingも日本語で行う
