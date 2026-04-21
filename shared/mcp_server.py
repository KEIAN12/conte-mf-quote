#!/usr/bin/env python3
"""CONTE MF見積作成プラグインのMCPサーバー

プロトコル: Model Context Protocol (stdio JSON-RPC 2.0)
実行環境: ユーザーのMac上でCoworkが自動起動する（sandboxではなくネイティブ）

ツール一覧（Claudeがskill内から呼び出す）:
  - mf_ping              : 接続確認（疎通テスト用）
  - mf_me                : 連携中ユーザー情報取得 / 未セットアップ検知
  - mf_setup             : 初回OAuth連携（Client Secret入力→ブラウザで認可）
  - mf_clear_auth        : Keychainからトークンを削除（連携解除）
  - mf_search_partners   : 取引先検索
  - mf_list_departments  : 取引先の部門一覧
  - mf_search_quotes     : 既存見積の検索（複製モード用）
  - mf_get_quote         : 見積1件取得
  - mf_duplicate_quote   : 既存見積を複製
  - mf_create_quote      : 新規見積下書き作成
  - mf_update_quote      : 見積のメタ情報（件名・日付等）更新
  - mf_add_item          : 品目追加
  - mf_delete_item       : 品目削除
  - mf_download_pdf      : 見積PDFをダウンロードしてファイル保存

すべて下書きまで。発行はMF管理画面から人間が行う運用。
"""

import json
import os
import sys
import traceback
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import token_manager
import mf_client
from mf_client import MFAPIError, MFGuardError
import oauth_setup


# ========== ツール定義 ==========

TOOLS = [
    {
        "name": "mf_ping",
        "description": "MCPサーバーの疎通確認。引数なし。'pong'とMF接続情報を返す。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "mf_me",
        "description": (
            "MF認証状態と連携事業者情報（office_name）を取得する。未セットアップ時は needs_setup: true を返す。"
            "※個人のemail/nameは取れない（MF API仕様）。個人識別はMF管理画面のoperator_idで行う。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "mf_setup",
        "description": (
            "MoneyForwardとの初回OAuth連携を実行する。"
            "Client Secretを受け取り、ブラウザでMF認可画面を開き、コールバックを待ってトークンをmacOS Keychainに保存する。"
            "最大5分のブロッキング処理。ユーザーがブラウザで認可ボタンを押すまで戻らない。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client_secret": {
                    "type": "string",
                    "description": "MF Client Secret（代表から共有された値）",
                },
                "open_browser": {
                    "type": "boolean",
                    "description": "自動でブラウザを開くか（デフォルトtrue）",
                    "default": True,
                },
            },
            "required": ["client_secret"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_clear_auth",
        "description": "Keychainに保存されたMF認証情報（トークン・Client Secret）を削除する。連携解除用。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "mf_search_partners",
        "description": "取引先を名前で検索する。部分一致。見積作成時の宛先選択に使う。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "取引先名の検索語（例: 〇〇市役所）"},
                "per_page": {"type": "integer", "default": 25},
                "page": {"type": "integer", "default": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_list_departments",
        "description": "指定した取引先の部門一覧を取得する。見積作成時のdepartment_id決定に必須。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partner_id": {"type": "string", "description": "取引先ID"},
            },
            "required": ["partner_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_search_quotes",
        "description": "既存の見積書を検索する（複製モードや過去参照用）。件名・宛先などで検索。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索キーワード（件名・宛先等）"},
                "per_page": {"type": "integer", "default": 25},
                "page": {"type": "integer", "default": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_get_quote",
        "description": "指定したIDの見積書を取得する。",
        "inputSchema": {
            "type": "object",
            "properties": {"quote_id": {"type": "string"}},
            "required": ["quote_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_duplicate_quote",
        "description": "既存の見積書を複製し、新しい下書きを作成する。複製先のquote_idを返す。",
        "inputSchema": {
            "type": "object",
            "properties": {"quote_id": {"type": "string"}},
            "required": ["quote_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_create_quote",
        "description": (
            "新規見積書を下書きとして作成する。payloadはMF Invoice API v3のQuote作成仕様に準拠。"
            "必須: department_id, quote_date, title。items配列で品目を指定。excise_type='boolean'で税抜表示。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "Quote作成ペイロード（詳細はapi-endpoints.md参照）",
                },
            },
            "required": ["payload"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_update_quote",
        "description": "既存の見積書のメタ情報（件名・日付・部門等）を更新する。品目個別編集はadd-item/delete-itemを使う。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string"},
                "payload": {"type": "object", "description": "更新するフィールドだけ入れる"},
            },
            "required": ["quote_id", "payload"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_add_item",
        "description": "見積書に品目を1つ追加する。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string"},
                "item": {
                    "type": "object",
                    "description": "品目（name, price必須。quantity, unit, excise, detail, is_deduct_withholding_tax任意）",
                },
            },
            "required": ["quote_id", "item"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_delete_item",
        "description": "見積書から品目を1つ削除する。item_idはget_quoteで取得。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string"},
                "item_id": {"type": "string"},
            },
            "required": ["quote_id", "item_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mf_download_pdf",
        "description": (
            "見積書のPDFをダウンロードしてローカルファイルに保存する。"
            "save_pathは絶対パス推奨。指定なしなら ~/Downloads に自動命名で保存。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string"},
                "save_path": {
                    "type": "string",
                    "description": "保存先の絶対パス（省略時は ~/Downloads/見積書_<quote_id>.pdf）",
                },
            },
            "required": ["quote_id"],
            "additionalProperties": False,
        },
    },
]


# ========== ツール実装 ==========

def _tool_mf_ping(args: dict) -> dict:
    return {
        "status": "pong",
        "server": "conte-mf-quote",
        "keychain_service": "conte-mf-quote",
    }


def _tool_mf_me(args: dict) -> dict:
    """認証状態と連携事業者情報を返す。

    MF Invoice API には /me エンドポイントがないため、/office を呼んで確認する。
    取れる情報は事業者名（株式会社CONTE等）。ユーザー個人のemail/nameは取れない。
    個人識別はMF管理画面側の operator_id/履歴で行う運用。
    """
    data = token_manager.load()
    if not data.get("access_token"):
        return {
            "authenticated": False,
            "needs_setup": True,
            "message": "MFトークンが保存されていません。mf_setup で初回セットアップをしてください。",
        }
    try:
        office = mf_client.get_office()
    except MFAPIError as e:
        if e.status == 401:
            return {
                "authenticated": False,
                "needs_setup": True,
                "message": "認証が無効です。mf_setup で再セットアップしてください。",
            }
        raise
    block = office.get("data", office) if isinstance(office, dict) else {}
    attrs = block.get("attributes", {}) if isinstance(block, dict) else {}
    office_name = (
        block.get("name") or attrs.get("name")
        or block.get("office_name") or attrs.get("office_name") or ""
    )
    return {
        "authenticated": True,
        "needs_setup": False,
        "office_name": office_name,
        "raw_office": office,
    }


def _tool_mf_setup(args: dict) -> dict:
    client_secret = args["client_secret"].strip()
    open_browser = args.get("open_browser", True)
    result = oauth_setup.run_setup(client_secret, open_browser=open_browser)
    office = result.get("office_name", "")
    msg = f"🎉 セットアップ完了: {office}" if office else "🎉 セットアップ完了（トークン保存済み）"
    return {
        "status": "completed",
        "office_name": office,
        "message": msg,
    }


def _tool_mf_clear_auth(args: dict) -> dict:
    token_manager.clear()
    return {"status": "cleared", "message": "Keychainから認証情報を削除しました。"}


def _tool_mf_search_partners(args: dict) -> dict:
    return mf_client.list_partners(
        args.get("query"),
        per_page=args.get("per_page", 25),
        page=args.get("page", 1),
    )


def _tool_mf_list_departments(args: dict) -> dict:
    return mf_client.list_departments(args["partner_id"])


def _tool_mf_search_quotes(args: dict) -> dict:
    return mf_client.list_quotes(
        args.get("query"),
        per_page=args.get("per_page", 25),
        page=args.get("page", 1),
    )


# MF クラウド請求書の管理画面URL生成ヘルパー
# 返り値に web_url を付加して、ユーザーに「MFで見る」リンクを提示できるようにする
MF_WEB_BASE = "https://invoice.moneyforward.com"


def _extract_quote_id(result: Any) -> Optional[str]:
    """API レスポンスから quote_id を抽出。トップレベル or data 配下どちらにも対応。"""
    if isinstance(result, dict):
        if "id" in result:
            return str(result["id"])
        data = result.get("data")
        if isinstance(data, dict) and "id" in data:
            return str(data["id"])
    return None


def _attach_web_url(result: Any) -> Any:
    """見積書レスポンスに MF 管理画面の URL を付加する"""
    qid = _extract_quote_id(result)
    if qid and isinstance(result, dict):
        result["web_url"] = f"{MF_WEB_BASE}/quotes/{qid}"
    return result


def _tool_mf_get_quote(args: dict) -> dict:
    return _attach_web_url(mf_client.get_quote(args["quote_id"]))


def _tool_mf_duplicate_quote(args: dict) -> dict:
    return _attach_web_url(mf_client.duplicate_quote(args["quote_id"]))


def _tool_mf_create_quote(args: dict) -> dict:
    return _attach_web_url(mf_client.create_quote(args["payload"]))


def _tool_mf_update_quote(args: dict) -> dict:
    return _attach_web_url(mf_client.update_quote(args["quote_id"], args["payload"]))


def _tool_mf_add_item(args: dict) -> dict:
    return mf_client.add_quote_item(args["quote_id"], args["item"])


def _tool_mf_delete_item(args: dict) -> dict:
    mf_client.delete_quote_item(args["quote_id"], args["item_id"])
    return {"status": "deleted"}


def _tool_mf_download_pdf(args: dict) -> dict:
    quote_id = args["quote_id"]
    save_path = args.get("save_path")
    if not save_path:
        downloads = os.path.expanduser("~/Downloads")
        os.makedirs(downloads, exist_ok=True)
        save_path = os.path.join(downloads, f"見積書_{quote_id}.pdf")
    # 絶対パスに正規化
    save_path = os.path.abspath(os.path.expanduser(save_path))
    # 親ディレクトリを作成
    parent = os.path.dirname(save_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    pdf_bytes = mf_client.download_quote_pdf(quote_id)
    with open(save_path, "wb") as f:
        f.write(pdf_bytes)
    return {
        "status": "saved",
        "path": save_path,
        "size_bytes": len(pdf_bytes),
    }


TOOL_HANDLERS = {
    "mf_ping": _tool_mf_ping,
    "mf_me": _tool_mf_me,
    "mf_setup": _tool_mf_setup,
    "mf_clear_auth": _tool_mf_clear_auth,
    "mf_search_partners": _tool_mf_search_partners,
    "mf_list_departments": _tool_mf_list_departments,
    "mf_search_quotes": _tool_mf_search_quotes,
    "mf_get_quote": _tool_mf_get_quote,
    "mf_duplicate_quote": _tool_mf_duplicate_quote,
    "mf_create_quote": _tool_mf_create_quote,
    "mf_update_quote": _tool_mf_update_quote,
    "mf_add_item": _tool_mf_add_item,
    "mf_delete_item": _tool_mf_delete_item,
    "mf_download_pdf": _tool_mf_download_pdf,
}


# ========== JSON-RPC over stdio ==========

PROTOCOL_VERSION = "2024-11-05"

def _write_message(msg: dict) -> None:
    """stdoutに1行JSONを書く（MCP stdio transportはline-delimited）"""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _make_response(req_id: Any, result: Any = None, error: Optional[dict] = None) -> dict:
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def _make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return _make_response(req_id, error=err)


def _handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": {
            "name": "conte-mf-quote",
            "version": "0.2.4",
        },
    }


def _handle_tools_list(params: dict) -> dict:
    return {"tools": TOOLS}


def _handle_tools_call(params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments", {}) or {}
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {
            "content": [{"type": "text", "text": f"未知のツール: {name}"}],
            "isError": True,
        }
    try:
        result = handler(args)
        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
    except MFGuardError as e:
        msg = f"⚠️ 安全ガード: {e}"
        return {"content": [{"type": "text", "text": msg}], "isError": True}
    except MFAPIError as e:
        msg = f"MF APIエラー (HTTP {e.status}): {e.body}"
        return {"content": [{"type": "text", "text": msg}], "isError": True}
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        msg = f"エラー: {e}\n{tb}"
        return {"content": [{"type": "text", "text": msg}], "isError": True}


def _dispatch(req: dict) -> Optional[dict]:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {}) or {}

    # notification（id無し）は返信しない
    is_notification = req_id is None

    try:
        if method == "initialize":
            result = _handle_initialize(params)
        elif method == "initialized" or method == "notifications/initialized":
            return None
        elif method == "tools/list":
            result = _handle_tools_list(params)
        elif method == "tools/call":
            result = _handle_tools_call(params)
        elif method == "ping":
            result = {}
        else:
            if is_notification:
                return None
            return _make_error(req_id, -32601, f"Method not found: {method}")
    except Exception as e:
        if is_notification:
            return None
        tb = traceback.format_exc(limit=3)
        return _make_error(req_id, -32603, f"Internal error: {e}", data=tb)

    if is_notification:
        return None
    return _make_response(req_id, result=result)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            # パース不能はエラー返信（id不明なのでnull）
            _write_message(_make_error(None, -32700, "Parse error"))
            continue

        # バッチリクエストへの対応（MCPでは通常使わないが念のため）
        if isinstance(req, list):
            responses = []
            for single in req:
                resp = _dispatch(single)
                if resp is not None:
                    responses.append(resp)
            if responses:
                sys.stdout.write(json.dumps(responses, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            continue

        resp = _dispatch(req)
        if resp is not None:
            _write_message(resp)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except BrokenPipeError:
        sys.exit(0)
