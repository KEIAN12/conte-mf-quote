# MF Invoice API v3 — Quote エンドポイント仕様

見積書作成・更新時に組み立てるJSONペイロードの構造を記載。Claudeがpayloadを組むときの参照。

## Quote作成（POST /quotes）

### 最小ペイロード

```json
{
  "department_id": "xxxxxxxx",
  "quote_date": "2026-04-20",
  "title": "件名",
  "excise_type": "boolean",
  "items": [
    {
      "name": "項目名",
      "quantity": 1,
      "price": 10000,
      "unit": "式",
      "excise": "ten_percent",
      "detail": "補足説明（任意）"
    }
  ]
}
```

### 主要フィールド

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `department_id` | string | ✅ | 取引先の部門ID（`list-departments`で取得） |
| `quote_date` | string (YYYY-MM-DD) | ✅ | 発行日（通常は今日） |
| `quote_expired_date` | string (YYYY-MM-DD) | 任意 | 有効期限。省略時は発行日+30日 |
| `title` | string | ✅ | 件名 |
| `memo` | string | 任意 | 備考 |
| `excise_type` | string | 任意 | 消費税の扱い: `boolean` = 税抜表示、`internal_tax` = 税込表示 |
| `quote_number` | string | 任意 | 省略時はMFが自動採番（基本的に省略する） |
| `note` | string | 任意 | 見積書末尾のメモ |
| `tags` | string[] | 任意 | タグ |
| `items` | array | 任意 | 品目配列（空でも作成可、後からadd-item） |

### excise_type について

- **通常は `"boolean"` を指定**（税抜表示=小計+消費税の形式）
- 「税込〇〇円で出したい」という要望があった場合のみ `"internal_tax"` を使う

### 品目（item）のフィールド

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `name` | string | ✅ | 品目名 |
| `quantity` | number | 任意 | 数量。省略時は 1 |
| `price` | number | ✅ | 単価（税抜） |
| `unit` | string | 任意 | 単位（式/時間/本/点/個/etc） |
| `excise` | string | 任意 | 税区分: `ten_percent`（10%）/ `eight_percent_as_reduced_tax_rate`（軽減8%）/ `tax_free`（非課税）。省略時は `ten_percent` |
| `detail` | string | 任意 | 補足説明（改行で複数行可） |
| `note` | string | 任意 | 品目内メモ |

### 例: 配信業務の見積（〇〇市役所向け）

```json
{
  "department_id": "abc123",
  "quote_date": "2026-04-20",
  "title": "市民フォーラム 第3回 配信",
  "excise_type": "boolean",
  "items": [
    {
      "name": "事前準備・会場下見",
      "quantity": 1,
      "price": 18000,
      "unit": "式",
      "excise": "ten_percent"
    },
    {
      "name": "機材費一式",
      "quantity": 1,
      "price": 40000,
      "unit": "式",
      "excise": "ten_percent",
      "detail": "カメラ・配信用PC・キャプチャ・配線他"
    },
    {
      "name": "機材運搬・設営・撤収費",
      "quantity": 1,
      "price": 15000,
      "unit": "式",
      "excise": "ten_percent"
    },
    {
      "name": "配信オペレーター費",
      "quantity": 4,
      "price": 8000,
      "unit": "時間",
      "excise": "ten_percent"
    },
    {
      "name": "音響費",
      "quantity": 1,
      "price": 15000,
      "unit": "式",
      "excise": "ten_percent",
      "detail": "機材＋オペレーター"
    },
    {
      "name": "アーカイブ編集・納品費",
      "quantity": 1,
      "price": 10000,
      "unit": "式",
      "excise": "ten_percent"
    },
    {
      "name": "進行管理費",
      "quantity": 1,
      "price": 20000,
      "unit": "式",
      "excise": "ten_percent",
      "detail": "打合せ費 ¥10,000 含む"
    }
  ]
}
```

この例: 小計¥150,000、消費税¥15,000、合計¥165,000

## Quote更新（PUT /quotes/{id}）

作成時と同じ構造。ただし `items` は**上書き**にならないことに注意。品目の個別編集は `add-item` / `delete-item` を使う（PUT items エンドポイントは存在しない仕様のため）。

タイトルや日付、部門などを変えたい時のみPUT /quotes/{id}を使う。

## Quote複製（POST /quotes/{id}/duplicate）

ペイロード不要。複製先の新しいquote_idが返る。複製直後はすべての項目が引き継がれているので、必要に応じて add-item / delete-item / update でアレンジする。

## 品目追加（POST /quotes/{quote_id}/items）

1品目追加。上記「品目のフィールド」と同じ構造。

## 品目削除（DELETE /quotes/{quote_id}/items/{item_id}）

1品目削除。既存の item_id は `get-quote` で取得。

## PDFダウンロード（GET /quotes/{quote_id}.pdf）

バイナリ返却。そのままファイルに保存する。

## 金額配分ロジック（Claudeが使うときの参考）

ユーザーが「税別18万」と言ったら税抜合計180,000を目標に項目配分する。

**目安（配信案件の場合の配分比率）**：
- 事前準備・下見: 10〜12%
- 機材費: 20〜25%
- 運搬・設営: 8〜10%
- オペレーター: 20〜25%（時給単価×時間）
- 音響: 8〜10%
- 編集・納品: 5〜8%
- 進行管理費: 10〜15%

**金額が端数になる場合**：1,000円単位で丸めて、進行管理費で調整するのが自然。

## 注意事項

- `quote_number` は基本省略（MFが自動採番）
- 過去のテスト実装で `tax_type` フィールドを試したが、MF APIは `excise_type` を使う
- 品目の `quantity` は整数でも小数（3.5時間 等）でもOK
- 発行前は `status: "draft"`、明示的に発行するまで下書きのまま
