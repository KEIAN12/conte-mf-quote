#!/usr/bin/env python3
"""MF OAuth初回セットアップスクリプト

実行時の流れ:
  1. Client Secretを入力プロンプトで受け取る
  2. ローカルHTTPサーバー(localhost:8080)を起動
  3. デフォルトブラウザでMF認可URLを開く
  4. ユーザーがMFにログイン→認可
  5. コールバックで認可コードを受け取る
  6. トークンエンドポイントで交換
  7. Keychainに保存
  8. 連携確認（/meエンドポイントで自分の情報取得）

Usage:
  python3 setup.py                    # 対話型でClient Secret入力
  MF_CLIENT_SECRET=xxx python3 setup.py  # 環境変数経由（非対話型）
"""

import base64
import http.server
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional

# shared/ をimport pathに追加
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "shared"))

from config import (
    CLIENT_ID, SCOPES, REDIRECT_URI,
    AUTHORIZE_URL, TOKEN_URL,
)
import token_manager
import mf_client


# コールバックで受け取ったcodeを格納するグローバル
_received_code: Optional[str] = None
_received_error: Optional[str] = None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """認可コードを受け取るハンドラ"""

    def do_GET(self):
        global _received_code, _received_error
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        if "error" in params:
            _received_error = params["error"][0]
            self._respond_html(
                "認証エラー",
                f"<p>エラー: {_received_error}</p>"
                f"<p>このタブを閉じてターミナルに戻ってください。</p>",
            )
            return

        if "code" in params:
            _received_code = params["code"][0]
            self._respond_html(
                "✅ 認証成功",
                "<p>CONTE MF見積作成プラグインの連携が完了しました。</p>"
                "<p>このタブは閉じていただいて大丈夫です。</p>",
            )
            return

        self._respond_html("不正なリクエスト", "<p>codeもerrorも含まれていません</p>")

    def log_message(self, format, *args):
        # HTTPログを標準エラーに出さない
        pass

    def _respond_html(self, title: str, body_html: str):
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 500px; margin: 100px auto;
       padding: 40px; text-align: center; color: #333; }}
h1 {{ color: #0066cc; }}
</style>
</head><body>
<h1>{title}</h1>
{body_html}
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def check_port_available(port: int) -> bool:
    """ポートが使用可能か確認"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_callback_server(port: int = 8080) -> http.server.HTTPServer:
    """コールバックサーバーを別スレッドで起動"""
    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def build_authorize_url(client_secret: str) -> str:
    """認可URLを組み立て"""
    # stateには現在時刻を入れる（CSRF対策）
    state = str(int(time.time()))
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, client_secret: str) -> dict:
    """認可コードをアクセストークン・リフレッシュトークンと交換"""
    creds = f"{CLIENT_ID}:{client_secret}".encode()
    auth = base64.b64encode(creds).decode()

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"トークン取得失敗 (HTTP {e.code}): {err_body}\n"
            "Client Secretが正しいか確認してください。"
        )


def main():
    print("=" * 60)
    print("CONTE MF見積作成プラグイン 初回セットアップ")
    print("=" * 60)
    print()

    # Client Secret取得（環境変数 or 対話）
    client_secret = os.environ.get("MF_CLIENT_SECRET")
    if not client_secret:
        print("代表（吉口さん）からもらったMF Client Secretを入力してください。")
        print("（入力は画面に表示されません）")
        import getpass
        client_secret = getpass.getpass("Client Secret: ").strip()

    if not client_secret:
        print("Client Secretが空です。中止します。")
        sys.exit(1)

    # ポート確認
    if not check_port_available(8080):
        print("⚠️ localhost:8080が既に使われています。")
        print("他のプロセス（開発サーバー等）を終了してから再実行してください。")
        sys.exit(1)

    # サーバー起動
    server = start_callback_server(8080)
    print("ローカルサーバー起動: http://localhost:8080")
    print()

    # 認可URLを開く
    auth_url = build_authorize_url(client_secret)
    print("ブラウザで認可画面を開きます...")
    print(f"  URL: {auth_url[:80]}...")
    print()
    webbrowser.open(auth_url)
    print("ブラウザでMFにログインして「許可」を押してください。")
    print("（ブラウザが開かない場合は、上のURLを手動で開いてください）")
    print()

    # コールバック待ち（最大5分）
    print("認可を待っています...")
    timeout = time.time() + 300
    while _received_code is None and _received_error is None:
        if time.time() > timeout:
            print("タイムアウト（5分）。再実行してください。")
            server.shutdown()
            sys.exit(1)
        time.sleep(0.5)

    server.shutdown()

    if _received_error:
        print(f"❌ 認可エラー: {_received_error}")
        sys.exit(1)

    print("✅ 認可コード取得")

    # トークン交換
    print("トークンを取得中...")
    tokens = exchange_code_for_tokens(_received_code, client_secret)
    print("✅ トークン取得")

    # 保存
    token_manager.save({
        "client_secret": client_secret,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": int(time.time()) + tokens.get("expires_in", 3600),
    })
    print("✅ Keychainに保存")

    # 連携確認
    try:
        me = mf_client.get_me()
        # /me レスポンス構造はMF仕様に依存、柔軟に読む
        user = me.get("data", me) if isinstance(me, dict) else {}
        email = (user.get("email")
                 or user.get("attributes", {}).get("email")
                 or "（取得できませんでした）")
        name = (user.get("name")
                or user.get("attributes", {}).get("name")
                or "")
        token_manager.update(user_email=email)
        print()
        print("=" * 60)
        print("🎉 セットアップ完了")
        print("=" * 60)
        print(f"  連携ユーザー: {name} ({email})")
        print()
        print("以後、Coworkで「見積作って」や /mf-quote で使えます。")
    except Exception as e:
        print(f"⚠️ 連携確認に失敗しましたが、トークンは保存されました: {e}")


if __name__ == "__main__":
    main()
