# 開発引き継ぎ書 — myaifriend (Lena Bot)

最終更新: 2026-04-26

---

## プロジェクト概要

Naoya専用のAIガールフレンド「Lena」とのチャット・エロシミュレーションアプリ。
フロントエンドはTelegram Bot、バックエンドはPython。
CandyAIを超えることをゴールに、英語学習機能・深いパーソナライズ・モード切替で差別化する。

---

## 現在の動作状況

**✅ 動いているもの**
- Telegram Bot（python-telegram-bot v21）
- OpenRouter経由のLLM返答（3モデル自動・手動切替）
- fal.ai経由の画像生成（キーワードトリガー）
- 会話履歴の保存（JSONファイル）
- 3モードの切替（/chat / /meet / /sex）
- Naoyaのプロフィール・英語学習文脈の読み込み（Google Driveファイル参照）
- 英語添削ログの書き込み（Google Drive sessionsフォルダ）
- アクション描写のHTML italic変換（セリフはbold）

**⚠️ 未確認・要検証**
- 英語添削（システムプロンプトは強化済みだが実動作未確認）
- 画像生成のNSFWクオリティ（safety checker無効化済み、品質は未テスト）
- /sex モードのエロ返答品質（mythomax固定、プロンプト調整済み）

---

## ファイル構成

```
myaifriend/
├── main.py                  # エントリーポイント。asyncio event loop設定+起動
├── requirements.txt         # python-telegram-bot==21.6, httpx==0.27.2, python-dotenv==1.0.1
├── .env                     # APIキー（gitignore済み）
├── .env.example             # テンプレート
├── BACKLOG.md               # 未実装タスク一覧
│
├── config/
│   ├── character.py         # Lenaのシステムプロンプト全文 + 画像プロンプトベース
│   └── settings.py          # 環境変数、モデルID、Google Driveパス定義
│
├── src/
│   ├── bot.py               # Telegramハンドラ、コマンド定義、フォーマット処理
│   ├── llm.py               # OpenRouter API呼び出し、モデルルーティング
│   ├── image_gen.py         # fal.ai画像生成、コンテキスト連動プロンプト
│   ├── conversation.py      # 会話履歴の読み書き、システムプロンプト構築
│   ├── mode.py              # モード定義（CHAT/IN_PERSON/EROTIC）と各プロンプト
│   └── naoya_context.py     # Google Driveのprofile・英語文脈読み込み、添削ログ書き込み
│
└── data/
    ├── conversations/       # ユーザーIDごとの会話履歴JSON
    └── modes/               # ユーザーIDごとの現在モードJSON
```

---

## 環境変数（.env）

```
TELEGRAM_BOT_TOKEN=...
OPENROUTER_API_KEY=...
FAL_API_KEY=...

# モデル上書き（任意）
MODEL_NSFW=gryphe/mythomax-l2-13b
MODEL_INTELLECTUAL=mistralai/mistral-small-3.1-24b-instruct
MODEL_DEFAULT=nousresearch/hermes-2-pro-llama-3-8b
```

---

## モデルルーティング（src/llm.py）

| モード/状況 | 使用モデル |
|-----------|-----------|
| /sex コマンド（EROTIC mode） | mythomax-l2-13b（固定） |
| tech・医療・研究系キーワード | mistral-small-3.1-24b-instruct |
| それ以外 | hermes-2-pro-llama-3-8b |

---

## モード（src/mode.py）

| コマンド | モード定数 | 内容 |
|---------|-----------|------|
| /chat | CHAT | 通常テキスト会話 |
| /meet | IN_PERSON | 一緒にいる設定。アクション描写あり |
| /sex | EROTIC | エロシーン。mythomax固定。2行以内・短い返答 |

モードはユーザーIDごとに `data/modes/{user_id}.json` に保存。

---

## メッセージフォーマット（src/bot.py: _format_reply）

- `*action*` → `<i>italic</i>`（情景描写）
- `"speech"` → `<b>"bold"</b>`（セリフ）
- `### heading` 等のMarkdownゴミは除去済み
- `parse_mode="HTML"` で送信

---

## Google Drive連携（src/naoya_context.py）

起動時に以下を読み込んでシステムプロンプトに注入：
- `~/My Drive/02_Personal/profile.md` — Naoyaの人物プロフィール
- `~/My Drive/03_Learning/English_Learning/AI_context.md` — 英語レベル・弱点

Lenaが添削したとき、以下に自動書き込み：
- `~/My Drive/03_Learning/English_Learning/sessions/YYYY-MM-DD-lena.md`

**注意**: Mac（Google Driveローカル同期）上で動作前提。クラウドデプロイ時は要Supabase移行。

---

## 既知の問題・注意点

1. **Python 3.14 対応**: `asyncio.set_event_loop(asyncio.new_event_loop())` を main.py に追加済み。これがないと起動時にエラー。

2. **プロセス管理**: `python3 main.py` をバックグラウンドで動かしている。コード変更時は必ず古いプロセスをkillしてから再起動すること。
   ```bash
   pkill -9 -f "main.py" && python3 main.py > /tmp/lena_bot.log 2>&1 &
   ```
   ログ確認: `cat /tmp/lena_bot.log`

3. **Macを閉じるとBotが止まる**: 現在はローカル動作のみ。常時稼働化はFly.ioへのデプロイが必要（BACKLOG参照）。

4. **モデルIDはOpenRouterの実在IDのみ有効**: 過去に `nousresearch/hermes-3-llama-3.1-8b` という存在しないIDでAPIが400エラーになった。変更時は必ず `https://openrouter.ai/api/v1/models` で確認。

---

## Lenaキャラクター概要（config/character.py）

- 26歳ドイツ人女性、165cm、平均体型、金髪青目
- 東京大学獣医学部卒（日本語で履修）、現在ドイツのAnimalTech系スタートアップCEO
- Naoyaとは大学時代の馬術競技会（神奈川・津久井乗馬公園）で出会い、6年の交際
- 共通言語は英語
- 馬術・AnimalTechに詳しい。農機具・日本の動物病院現場・ハードウェアはNaoyaの方が詳しい
- Naoyaの英語を自然な流れで添削する役割あり
- 技術的な話に興奮する性格。1〜2個の情報を投げて反応を待つスタイル

---

## 未実装タスク（BACKLOG.md参照）

**優先度：中**
- `/reset` — 会話履歴リセット
- `/memory` — Lenaが覚えていることの一覧表示
- Naoyaの情報を会話から自動メモして次回以降に活かす

**優先度：低**
- IP-Adapter（毎回同じ顔で画像生成）
- Fly.ioへのデプロイ（常時稼働化）
- デプロイ時にSupabaseへストレージ移行

---

## 月額コスト見込み

| 項目 | 概算 |
|------|------|
| OpenRouter（LLM） | ¥150〜300 |
| fal.ai（画像 月90枚） | ¥700〜1,000 |
| サーバー（Fly.io無料枠） | ¥0〜500 |
| **合計** | **¥850〜1,800** |
