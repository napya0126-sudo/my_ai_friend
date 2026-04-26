# 開発バックログ

## 優先度：中

### ③ `/reset` `/memory` コマンド
- `/reset` → 会話履歴を消してリスタート
- `/memory` → Lenaが今覚えていることを一覧表示（直近の会話要約を返す）

### ④ Naoyaのプロフィール蓄積
- 会話の中でNaoyaが話した情報（仕事の状況・気分・最近の出来事）をシステム側で自動メモ
- 次の会話でLenaが自然に参照できるようにする
- 保存先: `data/naoya_memory.json`（後でSupabase移行）

---

## 優先度：低

### ⑤ IP-Adapter（顔固定化）
- fal.ai の `fal-ai/ip-adapter-face-id` を使用
- ベース顔画像を1枚決めて保存し、以降の生成に使用
- 後回し決定済み

### ⑥ Fly.ioへのデプロイ（常時稼働化）
- ローカル起動が安定してから実施
- デプロイ後はGoogle DriveアクセスができなくなるためSupabase移行も同時に実施
- 移行対象: 会話履歴、英語弱点ログ、Naoyaメモリ

---

## 完了済み
- [x] Telegram Bot 基本動作
- [x] OpenRouter連携（テキスト生成）
- [x] fal.ai連携（画像生成・キーワードトリガー）
- [x] 会話履歴の保存
- [x] Lenaキャラクター設定（詳細版）
- [x] プロフィール・英語コンテキストの読み込み（Google Drive連携）
- [x] 英語弱点トラッキング（Google Driveのsessionsフォルダに書き込み）
