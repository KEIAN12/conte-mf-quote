# 管理者ガイド（吉口さん用）

社内配布・運用・トラブル対応のための管理者用マニュアル。

---

## 📦 全体アーキテクチャ

```
┌─ GitHub (Public Public)  ──── https://github.com/KEIAN12/conte-mf-quote
│     ├ marketplace.json       ← Cowork が読むメタデータ
│     └ プラグイン本体（Pythonコード、SKILL.md 等）
│
├─ MF Developer Portal  ──── OAuth アプリ「claude-agent」
│     ├ Client ID:     238122083351420  （ソースに埋め込み、公開OK）
│     └ Client Secret: 各社員に個別配布 → 各自のKeychainに保存
│
└─ 各社員の Mac
      ├ Cowork（Claude Desktop）
      ├ インストール済みプラグイン
      └ Keychain（service=conte-mf-quote）
            ├ client_secret
            ├ access_token
            └ refresh_token
```

**重要なポイント：**
- Client Secret は**ソースに埋め込まない**。各社員が初回セットアップ時に入力し、Keychainに保存される
- トークンの管理は各自の Mac 内で完結（サーバー管理なし）
- 見積書の承認・発行は MF 管理画面で人間が行う（Claude からは発行不可）

---

## 🚀 社員への配布フロー

### 準備するもの
- [ ] Zoom または画面共有ツール
- [ ] MF Client Secret（セキュアに渡せる手段：1Password共有、口頭、暗号化メール等）
- [ ] [USER-GUIDE.md](USER-GUIDE.md) のリンク or PDF

### 配布手順（社員1人につき10分）

1. **画面共有で一緒にインストール**
   - USER-GUIDE.md のインストール手順をその場でやる
   - マーケットプレイス追加 → インストール → `/mf-setup`

2. **Client Secret を渡す**
   - 推奨: 1Password 等のパスワードマネージャーで共有
   - 画面共有中に口頭でも可（後でログに残らない）
   - **絶対にやってはいけない**: Slack・メールに平文で貼る

3. **動作確認**
   - `/mf-quote` で試しに見積を1つ作成（下書きなのであとで削除OK）
   - MF の URL が表示されるか確認

4. **USER-GUIDE.md を渡す**
   - Slack DM に URL で共有
   - または PDF で渡す

---

## 🔄 アップデート配布の運用

### コード修正 → 配布までの流れ

```bash
# 1. ローカルで修正
cd ~/dev_project/CONTE_AIagent/conte-mf-quote
# ...修正作業...

# 2. バージョンを上げる（3箇所）
# .claude-plugin/plugin.json       → "version": "0.2.6"
# .claude-plugin/marketplace.json  → "version": "0.2.6"
# shared/mcp_server.py (line ~439) → "version": "0.2.6"

# 3. コミット & push
git add -A
git commit -m "feat(v0.2.6): 変更内容"
git push

# 4. 社員に連絡
# Slack で「Coworkのプラグイン画面で『更新』ボタンを押してください」
```

### 社員側の更新手順
Cowork → プラグイン → `Conte mf quote` → 「更新」ボタンを押す

**キャッシュで古いままの場合**: マーケットプレイスを削除して再追加（これで最新 fetch される）

---

## 🔒 セキュリティ運用

### Client Secret のローテーション（推奨: 3〜6ヶ月に1回）

1. [MF Developer Portal](https://biz.moneyforward.com/developer/) にログイン
2. 「claude-agent」アプリを開く
3. **「Client Secret を再発行」**
4. 旧 Secret は自動的に失効
5. 新 Secret を全社員に配布
6. 各社員は `/mf-setup` で再セットアップ

### 退職者対応
1. MF Developer Portal で該当者のアプリ連携を解除
2. Client Secret を再発行（他の社員にも新Secret配布が必要）
3. 退職者の Mac から Cowork・プラグインを削除してもらう（任意。どのみち新Secretで無効化される）

### Client Secret 漏洩の疑いがある場合
**即座に Client Secret を再発行**。上記と同じ手順。

---

## 🔧 GitHub リポの公開範囲管理

### 現状: Public（マーケットプレイス機能の仕様で Public 必須）

### Private 化するタイミングの判断
- 全員のインストールが完了
- バージョンが安定している（1ヶ月以上アップデートなし）

### Private 化の手順
```bash
gh repo edit KEIAN12/conte-mf-quote --visibility private --accept-visibility-change-consequences
```

### Private 化後の挙動
- ✅ インストール済みの人はそのまま使える
- ❌ プラグインの「更新」ボタンは無効化
- ❌ 新規社員の追加ができない
- ❌ マーケットプレイスの再同期でエラー

### アップデート配布時の一時Public化
```bash
# 1. 一時的に Public
gh repo edit KEIAN12/conte-mf-quote --visibility public --accept-visibility-change-consequences

# 2. 社員に更新依頼
# 3. 全員更新完了確認後

# 4. Private に戻す
gh repo edit KEIAN12/conte-mf-quote --visibility private --accept-visibility-change-consequences
```

---

## 🆘 トラブルシューティング（社員からの質問対応）

### 「連携が切れた」と出る
→ 社員に `/mf-setup` で再セットアップを案内。

### 「このアプリは許可されていません」
→ MF Developer Portal の「claude-agent」アプリの**ユーザー追加**画面で、該当社員を追加する。

### プラグインが起動しない
→ Cowork の再起動 or マーケットプレイスの削除→再追加。

### 間違えて見積書を大量に作ってしまった
→ MF 管理画面から手動で削除。プラグインからは削除できない仕様（安全策）。

### 「Client Secret」ってなんですか？
→ 代表から渡される英数字の文字列。MFとClaudeをつなぐためのパスワードのようなもの。各社員固有ではなく全社員で同じもの。

---

## 📋 新規社員追加時のチェックリスト

- [ ] MF Developer Portal の「claude-agent」アプリに該当社員を追加
- [ ] MF クラウド請求書で該当社員のアカウントが作成されていることを確認
- [ ] Client Secret をセキュアに共有（1Password等）
- [ ] 画面共有でインストール（USER-GUIDE.md 参照）
- [ ] 動作確認（試しに1つ見積作成→MF画面で確認→削除）

---

## 🗑 完全撤去手順（プロジェクト終了時）

### 各社員の Mac で
1. Cowork → プラグイン → Conte mf quote → アンインストール
2. Keychain Access アプリで `conte-mf-quote` で検索して関連エントリを削除
3. 必要ならマーケットプレイス `conte-plugins` も削除

### 管理側
1. MF Developer Portal で「claude-agent」アプリを削除（または無効化）
2. GitHub リポ `KEIAN12/conte-mf-quote` を Archive または Private 化

---

## 📚 参考リソース

- [USER-GUIDE.md](USER-GUIDE.md) — 社員配布用のマニュアル
- [README.md](../README.md) — 技術者向けの詳細説明
- [MF Invoice API v3 ドキュメント](https://invoice.moneyforward.com/docs/api/v3/index.html)
- [MF Developer Portal](https://biz.moneyforward.com/developer/)

---

## 🏗 今後の拡張アイデア

- 請求書作成機能（見積→請求書転記）
- 経費精算プラグイン
- プロジェクト管理プラグイン（Notion連携）

これらは同じ `conte-plugins` マーケットプレイスに追加可能。
`marketplace.json` の `plugins` 配列に追記するだけで配布できる。
