#!/usr/bin/env python3
"""MF見積書操作スクリプト（サブコマンド形式）

使い方:
  python3 mf.py search-partners <query>           取引先を検索
  python3 mf.py list-departments <partner_id>     取引先の部門一覧
  python3 mf.py search-quotes <query>             見積を検索（複製用）
  python3 mf.py get-quote <quote_id>              見積を1件取得（複製前に中身確認）
  python3 mf.py duplicate <quote_id>              見積を複製（新規下書き作成）
  python3 mf.py create <payload_json_file>        新規見積を作成（JSONファイル渡し）
  python3 mf.py update <quote_id> <payload_json>  見積を更新
  python3 mf.py add-item <quote_id> <item_json>   品目を追加
  python3 mf.py delete-item <quote_id> <item_id>  品目を削除
  python3 mf.py pdf <quote_id> [output_path]      PDFダウンロード
  python3 mf.py me                                連携中ユーザー情報を表示

出力は基本JSON。エラーはstderrに出してexit 1。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "shared"))

import mf_client


def _out(obj):
    """JSONを標準出力に書き出す"""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _err(msg: str, code: int = 1):
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(code)


def _read_json_arg(arg: str) -> dict:
    """引数がファイルパスならファイル読み込み、そうでなければJSON文字列としてパース"""
    if os.path.isfile(arg):
        with open(arg, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(arg)


def cmd_search_partners(args):
    if not args:
        _err("検索クエリが必要です")
    result = mf_client.list_partners(query=args[0], per_page=10)
    # 結果から必要最小限の情報だけ抜く
    items = result.get("data", result.get("partners", []))
    if isinstance(items, dict):
        items = [items]
    trimmed = []
    for p in items:
        attrs = p.get("attributes", p) if isinstance(p, dict) else {}
        trimmed.append({
            "id": p.get("id") if isinstance(p, dict) else None,
            "name": attrs.get("name"),
            "code": attrs.get("code"),
            "name_suffix": attrs.get("name_suffix"),
        })
    _out({"partners": trimmed, "count": len(trimmed)})


def cmd_list_departments(args):
    if not args:
        _err("partner_idが必要です")
    result = mf_client.list_departments(args[0])
    items = result.get("data", result.get("departments", []))
    if isinstance(items, dict):
        items = [items]
    trimmed = []
    for d in items:
        attrs = d.get("attributes", d) if isinstance(d, dict) else {}
        trimmed.append({
            "id": d.get("id") if isinstance(d, dict) else None,
            "name": attrs.get("name"),
            "person_name": attrs.get("person_name"),
            "email": attrs.get("email"),
        })
    _out({"departments": trimmed})


def cmd_search_quotes(args):
    if not args:
        _err("検索クエリが必要です")
    result = mf_client.list_quotes(query=args[0], per_page=15)
    items = result.get("data", result.get("quotes", []))
    if isinstance(items, dict):
        items = [items]
    trimmed = []
    for q in items:
        attrs = q.get("attributes", q) if isinstance(q, dict) else {}
        trimmed.append({
            "id": q.get("id") if isinstance(q, dict) else None,
            "quote_number": attrs.get("quote_number"),
            "title": attrs.get("title"),
            "partner_name": attrs.get("partner_name"),
            "department_name": attrs.get("department_name"),
            "total_price": attrs.get("total_price"),
            "quote_date": attrs.get("quote_date"),
            "status": attrs.get("status"),
        })
    _out({"quotes": trimmed, "count": len(trimmed)})


def cmd_get_quote(args):
    if not args:
        _err("quote_idが必要です")
    _out(mf_client.get_quote(args[0]))


def cmd_duplicate(args):
    if not args:
        _err("quote_idが必要です")
    _out(mf_client.duplicate_quote(args[0]))


def cmd_create(args):
    if not args:
        _err("payload（JSON文字列またはファイルパス）が必要です")
    payload = _read_json_arg(args[0])
    _out(mf_client.create_quote(payload))


def cmd_update(args):
    if len(args) < 2:
        _err("quote_id と payload が必要です")
    payload = _read_json_arg(args[1])
    _out(mf_client.update_quote(args[0], payload))


def cmd_add_item(args):
    if len(args) < 2:
        _err("quote_id と item（JSON）が必要です")
    item = _read_json_arg(args[1])
    _out(mf_client.add_quote_item(args[0], item))


def cmd_delete_item(args):
    if len(args) < 2:
        _err("quote_id と item_id が必要です")
    mf_client.delete_quote_item(args[0], args[1])
    _out({"ok": True})


def cmd_pdf(args):
    if not args:
        _err("quote_idが必要です")
    quote_id = args[0]
    # 出力先はデフォルトで ~/Downloads/ （一時置き場）
    default_dir = os.path.expanduser("~/Downloads")
    output_path = args[1] if len(args) > 1 else os.path.join(default_dir, f"見積書_{quote_id}.pdf")
    pdf = mf_client.download_quote_pdf(quote_id)
    with open(output_path, "wb") as f:
        f.write(pdf)
    _out({"saved_to": output_path, "size_bytes": len(pdf)})


def cmd_me(args):
    _out(mf_client.get_me())


COMMANDS = {
    "search-partners": cmd_search_partners,
    "list-departments": cmd_list_departments,
    "search-quotes": cmd_search_quotes,
    "get-quote": cmd_get_quote,
    "duplicate": cmd_duplicate,
    "create": cmd_create,
    "update": cmd_update,
    "add-item": cmd_add_item,
    "delete-item": cmd_delete_item,
    "pdf": cmd_pdf,
    "me": cmd_me,
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        _err(f"不明なコマンド: {cmd}\n利用可能: {', '.join(COMMANDS.keys())}")

    try:
        COMMANDS[cmd](sys.argv[2:])
    except mf_client.MFAPIError as e:
        _err(f"MF API エラー (HTTP {e.status}): {e.body}")
    except RuntimeError as e:
        _err(str(e))
    except Exception as e:
        _err(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
