# Codex Auto Archive

[English](../README.md) · [简体中文](README.zh-CN.md) · **日本語** · [Español](README.es.md)

Codex 自身の Archive を自然言語で管理するローカル MCP プラグインです。無操作期間、明示的な完了、関連 PR/CI、除外、プレビュー、復元、定期確認に対応します。バックグラウンド処理は LLM を呼び出しません。会話の削除や Codex データファイルの直接編集は行いません。

**制約：** テストした Codex 0.160.0 では、独立した App Server が Desktop の実行状態を確実に把握できず、ピン情報も公開されていません。その場合は安全のためスキップします。初回は Dry Run です。Desktop の完全な無人自動アーカイブを保証するリリースではありません。[互換性](COMPATIBILITY.md)。

Python 3.11+、uv、Codex CLI を用意してください。

```bash
git clone https://github.com/Jineggegg/codex-auto-archive.git
cd codex-auto-archive
bash scripts/install.sh
```

Windows は `powershell -ExecutionPolicy Bypass -File scripts/install.ps1`。新しい Codex 会話を開き、`/hooks` でコマンドフックを確認・信頼してください。WSL と Windows のプロファイルは別です。

会話例：「7日間使わなかった会話をアーカイブ」「完了時の自動アーカイブを無効にして」「このプロジェクトを除外」「今後7日の対象をプレビュー」「昨日の自動アーカイブを復元」「言語を日本語に設定」。変更後は実際の設定を返します。明示的な有効化だけが Dry Run を解除します。

初期値：無操作30日、完了/PR/CI/Issue/Goalルールは個別にオフ、完了猶予30分、ピン保護オン、復元後7日保護、60分ごとに確認、1回最大20スレッド。バッチ処理はプレビューと確認が必要です。現在の会話は正確なIDを使用し、最低60秒遅延してアイドルを待ちます。

保守的=90日、標準=30日、積極的=7日。言語は auto/en/zh-CN/ja/es。[詳しい使い方とアンインストール](../README.md)。
