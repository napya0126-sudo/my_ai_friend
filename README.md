# my_ai_friend

Telegram 上で動作する、パーソナル向けの AI チャットボット（Lena）です。  
Claude / OpenRouter（NSFW 向けモデル）/ fal.ai（画像）などを組み合わせています。

## 機能（概要）

- テキスト会話（モード: チャット / 対面 / エロ）
- 会話履歴の **チャンネル分け**（`general` / `diary` / `erotic`）— 1 対 1 では `/ch` により切替
- 任意: **`.env` で `TELEGRAM_EROTIC_CHAT_ID` を指定すると、エロ会話を別の Telegram チャット（非公開スーパーグループ等）専用に分離**（下記「エロ専用 Telegram」）
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
| `TELEGRAM_EROTIC_CHAT_ID` | 任意。エロ専用の **スーパーグループ**のチャットID（例: `-1001234567890`）。**未設定なら 1 対 1 でも従来どおり `/sex` 可能** |

任意: `MODEL_NSFW`, `MODEL_CHAT` でモデル名を上書き可能（`.env.example` 参照）。

## エロ専用 Telegram（`TELEGRAM_EROTIC_CHAT_ID` を使う場合）

1. Telegram で **新しいグループ**を作成 → **「スーパーグループ」に更新**（人数や設定で可能なアプリ上で実行）。
2. そのスーパーグループに **あなたと Bot だけ**入れる（秘密の専用部屋に近い使い方）。
3. そのグループに **Bot を参加**（管理者推奨）。`chat.id`（通常は **負の数**のスーパーグループID）は、グループ内で動く ID 表示 Bot（例: RawData 系）の説明に従うか、一度だけログに出すなどして控えてください。
4. `TELEGRAM_EROTIC_CHAT_ID=-100...` を `.env` に記入し、**Bot を再起動**。

この設定が有効なとき、**1 対 1 では `/sex` やここでいう `erotic` チャンネルに切れません**（案内が表示されます）。エロは専用スーパーグループ内の会話でのみ行われます。`/daily` など日記用は 1 対 1 側のまま使えます。

**補足:** 映し出し専用の **Telegram「チャンネル」**（Channel）は、多くの場合コメント用の**別グループ**でやり取りします。**双方向の会話をそのまま分けたい**なら、まず**非公開スーパーグループ**に Bot を入れる形が扱いやすいです。

## Telegram の主要コマンド

| コマンド | 内容 |
|----------|------|
| `/chat` | テキストモード + `general` チャンネル |
| `/meet` | 対面モード + `general` チャンネル |
| `/sex` | エロモード + `erotic` チャンネル（`TELEGRAM_EROTIC_CHAT_ID` 設定中は 1 対 1 では使えない） |
| `/ch general` `/ch diary` `/ch erotic` | 会話履歴のチャンネル切替 |
| `/mode` | 現在のモードとチャンネル表示 |
| `/daily` `/done` | 日次インタビュー開始 / 手動終了 |
| `/photo` | 画像生成 |
| `/usage` | 利用状況 |
| `/help` | ヘルプ |

## データ上の「チャンネル」と Telegram の用語

- **会話DBのチャンネル**（`general` / `diary` / `erotic`）は、AI が参照する履歴の**論理区分**です。
- **Telegram 上**で分けたい場合は、上記 `TELEGRAM_EROTIC_CHAT_ID` により **専用の（通常は非公開）スーパーグループ**にエロ会話を寄せることができます。`TELEGRAM_EROTIC_CHAT_ID` を**書かなければ**、必須の「別 Telegram チャット」は不要で、1 対 1 だけで運用可能です。

Bot アカウント（BotFather で作った1つの Bot）を、**1 対 1 用スレッド**と**専用グループ**の両方に入れる、という使い方になります（Bot は1つで足ります）。

## 補足（パス）

`config/settings.py` 内で、日記出力先 `~/lena_diary` や Google Drive 同期パス（プロフィール・英語学習コンテキスト）を参照する場合があります。  
別環境ではパスを合わせるか、コードを環境向けに調整してください。

## ライセンス

リポジトリ利用者の責任のもとでご利用ください。API 利用規約・各サービスポリシーを遵守してください。
