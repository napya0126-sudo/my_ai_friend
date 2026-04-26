# my_ai_friend

Telegram 上で動作する、パーソナル向けの AI チャットボット（Lena）です。  
Claude / OpenRouter（NSFW 向けモデル）/ fal.ai（画像）などを組み合わせています。

## 機能（概要）

- テキスト会話（モード: チャット / 対面 / エロ）
- 会話履歴の **チャンネル分け**（`general` / `diary` / `erotic`）— 同一 Bot チャット内で `/ch` により切替
- `/daily` 日次インタビュー（振り返り）と Markdown エクスポート
- 画像生成（キーワード・文脈連動）
- 利用状況（トークン・概算費用）の `/usage` 集計

## 必要なもの

- Python 3.11 以上推奨
- 各種 API キー（下記 `.env`）

## セットアップ

```bash
cd my_ai_friend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env に TELEGRAM_BOT_TOKEN, OPENROUTER, FAL, ANTHROPIC, TAVILY を記入
python main.py
```

初回起動で SQLite（`data/lena.db`）が作成されます。  
会話用 JSON マイグレーションの仕様は `src/db.py` 参照。

## 環境変数

| 変数 | 説明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) で発行 |
| `OPENROUTER_API_KEY` | テキスト（NSFW ルート用モデル含む） |
| `FAL_API_KEY` | 画像生成 |
| `ANTHROPIC_API_KEY` | Claude（本番チャット・日次など） |
| `TAVILY_API_KEY` | 検索ツール用 |

任意: `MODEL_NSFW`, `MODEL_CHAT` でモデル名を上書き可能（`.env.example` 参照）。

## Telegram の主要コマンド

| コマンド | 内容 |
|----------|------|
| `/chat` | テキストモード + `general` チャンネル |
| `/meet` | 対面モード + `general` チャンネル |
| `/sex` | エロモード + `erotic` チャンネル |
| `/ch general` `/ch diary` `/ch erotic` | 会話履歴のチャンネル切替 |
| `/mode` | 現在のモードとチャンネル表示 |
| `/daily` `/done` | 日次インタビュー開始 / 手動終了 |
| `/photo` | 画像生成 |
| `/usage` | 利用状況 |
| `/help` | ヘルプ |

## 「チャンネル」と Telegram の違い

**Telegram 上に新しい「チャンネル」（公開配信用）を作る必要はありません。**  
ここでいうチャンネルは、**同じ 1 対 1 チャット内で、会話履歴を論理的に分ける**ための区分です。Bot は常に 1 つで問題ありません。

## 補足（パス）

`config/settings.py` 内で、日記出力先 `~/lena_diary` や Google Drive 同期パス（プロフィール・英語学習コンテキスト）を参照する場合があります。  
別環境ではパスを合わせるか、コードを環境向けに調整してください。

## ライセンス

リポジトリ利用者の責任のもとでご利用ください。API 利用規約・各サービスポリシーを遵守してください。
