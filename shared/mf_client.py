"""MoneyForward クラウド請求書 API v3 クライアント

全リクエストで自動的にアクセストークンを付与し、401時は1回だけリフレッシュして再試行する。
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Any, Optional
from config import API_BASE
import token_manager


class MFAPIError(Exception):
    """MF APIエラー"""
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"MF API {status}: {body}")


class MFGuardError(Exception):
    """安全ガード違反。発行済み・ロック済みの見積への書き込みをブロックする際に発生。"""
    pass


def _assert_editable(quote_id: str) -> dict:
    """見積が編集可能（=下書き かつ ロック解除）か確認する。

    編集不可ならMFGuardErrorをraiseする。呼び出し元は update/add_item/delete_item の先頭でこれを呼ぶ。

    Returns:
        取得した見積データ（呼び出し元で再利用できるよう）
    """
    quote = get_quote(quote_id)
    data = quote.get("data", quote) if isinstance(quote, dict) else {}
    if not isinstance(data, dict):
        data = {}

    quote_number = data.get("quote_number", "?")

    # is_locked: True なら編集禁止
    if data.get("is_locked") is True:
        raise MFGuardError(
            f"見積書No.{quote_number} はロック済みのため編集できません。"
            "MF画面でロックを解除してから再試行するか、複製して新しい下書きを作ってください。"
        )

    # posting_status: "default" 以外は発行系アクション済み
    posting = data.get("posting_status", "default")
    if posting and posting != "default":
        raise MFGuardError(
            f"見積書No.{quote_number} は発行済み（posting_status={posting}）のため編集できません。"
            "複製して新しい下書きを作ってください。"
        )

    # order_status/transmit_status も一応チェック（確定系）
    order = data.get("order_status", "default")
    if order and order not in ("default", "none"):
        raise MFGuardError(
            f"見積書No.{quote_number} は受注状態（order_status={order}）のため編集できません。"
            "複製して新しい下書きを作ってください。"
        )

    return data


def _request(method: str, path: str, body: Optional[dict] = None,
             query: Optional[dict] = None, _retry: bool = True) -> Any:
    """MF APIを叩く共通関数

    Args:
        method: HTTPメソッド
        path: /quotes 等のAPIパス（先頭スラッシュ）
        body: リクエストボディ（dict→JSON）
        query: URLクエリパラメータ
        _retry: 401時にリフレッシュしてリトライするか（内部用）

    Returns:
        レスポンスbody（JSON→dict / bytes for PDFs）
    """
    url = API_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    headers = {
        "Authorization": f"Bearer {token_manager.get_access_token()}",
        "Accept": "application/json",
    }

    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in ct:
                return json.loads(raw) if raw else {}
            # PDF等のバイナリ
            return raw
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        if e.code == 401 and _retry:
            # トークン切れの可能性→リフレッシュしてリトライ
            token_manager.refresh_access_token()
            return _request(method, path, body=body, query=query, _retry=False)
        raise MFAPIError(e.code, body_text)


# ========== Quote 見積書 ==========

def list_quotes(query: Optional[str] = None, per_page: int = 25, page: int = 1) -> dict:
    """見積書一覧を検索

    /quotes の `q` パラメータで検索。取引先(完全一致)・ステータス・件名等がヒット。
    """
    q: dict = {"per_page": per_page, "page": page}
    if query:
        q["q"] = query
    return _request("GET", "/quotes", query=q)


def get_quote(quote_id: str) -> dict:
    """見積書を1件取得"""
    return _request("GET", f"/quotes/{quote_id}")


def create_quote(payload: dict) -> dict:
    """見積書を新規作成（下書き）"""
    return _request("POST", "/quotes", body=payload)


def update_quote(quote_id: str, payload: dict) -> dict:
    """見積書を更新。発行済み・ロック済みはガードでブロック。"""
    _assert_editable(quote_id)
    return _request("PUT", f"/quotes/{quote_id}", body=payload)


def duplicate_quote(quote_id: str) -> dict:
    """既存見積書を複製

    MF Invoice API v3 には /quotes/{id}/duplicate エンドポイントが存在しないため、
    GET /quotes/{id} でペイロードを取り出し、再利用不可なフィールドを除いて POST /quotes する。
    複製後の見積番号は MF が自動採番する。
    """
    src = get_quote(quote_id)
    # レスポンスは {"data": {...}} かトップレベル直か、実装差異があるので両対応
    if isinstance(src, dict) and "data" in src and isinstance(src["data"], dict):
        base = src["data"]
    else:
        base = src if isinstance(src, dict) else {}

    # コピーしてはいけないフィールド（MF側が自動採番/生成するもの）
    strip_top = {
        "id", "quote_number", "pdf_url", "status", "posted_at",
        "ordered", "ordered_at", "converted_at", "converted_billing_id",
        "created_at", "updated_at", "document_number",
        "operator_id", "creator_id", "editor_id",
    }
    payload = {k: v for k, v in base.items() if k not in strip_top}

    # 品目（items）もidを落として渡す。MF公式仕様: フィールド名は price (not unit_price),
    # quantity, name, detail, unit, excise, is_deduct_withholding_tax。
    # GETレスポンスは price/quantity が文字列で返るので、POST時には数値に変換する。
    items = base.get("items") or []
    clean_items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        clean: dict = {}
        # 必ず name は入れる（空欄行も空文字で再現する）
        clean["name"] = it.get("name") or ""
        for k in ("detail", "unit", "excise"):
            if it.get(k) is not None:
                clean[k] = it[k]
        # price / quantity は文字列→数値に変換
        for numeric_key in ("price", "quantity"):
            v = it.get(numeric_key)
            if v is None or v == "":
                continue
            try:
                clean[numeric_key] = float(v)
            except (TypeError, ValueError):
                clean[numeric_key] = v
        if it.get("is_deduct_withholding_tax") is not None:
            clean["is_deduct_withholding_tax"] = it["is_deduct_withholding_tax"]
        clean_items.append(clean)
    if clean_items:
        payload["items"] = clean_items

    # department_idだけあれば部門は引き継げる。departmentオブジェクトは除去
    payload.pop("department", None)
    payload.pop("partner", None)

    # 複製元のdepartment_idを取り出す（ネストしているケースにフォールバック）
    if "department_id" not in payload:
        dept = base.get("department") or {}
        if isinstance(dept, dict) and dept.get("id"):
            payload["department_id"] = dept["id"]

    return create_quote(payload)


def delete_quote(quote_id: str) -> None:
    """見積書を削除"""
    _request("DELETE", f"/quotes/{quote_id}")


def add_quote_item(quote_id: str, item: dict) -> dict:
    """見積書に品目を追加。発行済み・ロック済みはガードでブロック。"""
    _assert_editable(quote_id)
    return _request("POST", f"/quotes/{quote_id}/items", body=item)


def delete_quote_item(quote_id: str, item_id: str) -> None:
    """見積書から品目を削除。発行済み・ロック済みはガードでブロック。"""
    _assert_editable(quote_id)
    _request("DELETE", f"/quotes/{quote_id}/items/{item_id}")


def download_quote_pdf(quote_id: str) -> bytes:
    """見積書をPDFとしてダウンロード"""
    return _request("GET", f"/quotes/{quote_id}.pdf")


# ========== Partner 取引先 ==========

def list_partners(query: Optional[str] = None, per_page: int = 25, page: int = 1) -> dict:
    """取引先一覧を検索

    /partners は `name` パラメータで部分一致検索（カンマ区切りで複数指定可）。
    `q` パラメータは存在しない。空クエリ時は全件（ページネーションあり）。
    """
    q: dict = {"per_page": per_page, "page": page}
    if query:
        q["name"] = query
    return _request("GET", "/partners", query=q)


def list_departments(partner_id: str) -> dict:
    """取引先の部門一覧"""
    return _request("GET", f"/partners/{partner_id}/departments")


def get_partner(partner_id: str) -> dict:
    """取引先を1件取得"""
    return _request("GET", f"/partners/{partner_id}")


# ========== Office 自分の事業者情報 ==========

def get_office() -> dict:
    """連携している事業者情報を取得（認証確認・連携ユーザー確認用）

    MF Invoice API には /me エンドポイントは存在しない。認証確認には /office を使う。
    """
    return _request("GET", "/office")


# 旧API名（後方互換のため残す。新コードは get_office を使う）
def get_me() -> dict:
    return get_office()


if __name__ == "__main__":
    # 簡易テスト
    import sys
    if len(sys.argv) < 2:
        print("Usage: mf_client.py [me|quotes|partners <query>]")
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "me":
            print(json.dumps(get_me(), indent=2, ensure_ascii=False))
        elif cmd == "quotes":
            q = sys.argv[2] if len(sys.argv) > 2 else None
            print(json.dumps(list_quotes(q), indent=2, ensure_ascii=False))
        elif cmd == "partners":
            q = sys.argv[2] if len(sys.argv) > 2 else None
            print(json.dumps(list_partners(q), indent=2, ensure_ascii=False))
        else:
            print(f"不明: {cmd}")
    except MFAPIError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
