"""MF OAuth初回セットアップ（ローカルHTTPサーバー起動→ブラウザで認可→トークン交換）

MCP Server のmf_setup ツールから呼ばれる。ユーザーのMacでネイティブ実行される前提。
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
import urllib.error
import webbrowser
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from config import (
    CLIENT_ID, SCOPES, REDIRECT_URI,
    AUTHORIZE_URL, TOKEN_URL,
)
import token_manager
import mf_client


_received_code: Optional[str] = None
_received_error: Optional[str] = None
_state: Optional[str] = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """認可コードを受け取るHTTPハンドラ"""

    def do_GET(self):
        global _received_code, _received_error
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        # stateチェック
        got_state = params.get("state", [""])[0]
        if _state and got_state != _state:
            _received_error = "state_mismatch"
            self._respond_html("認証エラー", "<p>stateが一致しません。セキュリティのため中断しました。</p>")
            return

        if "error" in params:
            _received_error = params["error"][0]
            self._respond_html(
                "認証エラー",
                f"<p>エラー: {_received_error}</p><p>このタブを閉じてCoworkに戻ってください。</p>",
            )
            return

        if "code" in params:
            _received_code = params["code"][0]
            self._respond_html(
                "✅ 認証成功",
                "<p>CONTE MF見積作成プラグインの連携が完了しました。</p>"
                "<p>このタブを閉じてCoworkに戻ってください。</p>",
            )
            return

        self._respond_html("不正なリクエスト", "<p>codeもerrorも含まれていません</p>")

    def log_message(self, format, *args):
        return  # 標準エラーにログを出さない

    def _respond_html(self, title: str, body_html: str):
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 520px; margin: 100px auto;
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


def _check_port(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _start_server(port: int) -> http.server.HTTPServer:
    srv = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _build_authorize_url() -> str:
    global _state
    _state = str(int(time.time()))
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": _state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _exchange_code(code: str, client_secret: str) -> dict:
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
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"トークン取得失敗 (HTTP {e.code}): {err}\n"
            "Client Secretが正しいか確認してください。"
        )


def run_setup(client_secret: str, open_browser: bool = True, timeout_sec: int = 300) -> dict:
    """OAuth初回セットアップを1関数で実行。

    Args:
        client_secret: ユーザーが入力したMF Client Secret
        open_browser: True なら自動でブラウザを開く
        timeout_sec: コールバック待ちのタイムアウト（秒）

    Returns:
        dict with keys: user_email, user_name, authorize_url (参考用)

    Raises:
        RuntimeError: 失敗時
    """
    global _received_code, _received_error, _state
    _received_code = None
    _received_error = None

    if not client_secret:
        raise RuntimeError("Client Secretが空です。")

    if not _check_port(8080):
        raise RuntimeError(
            "localhost:8080が既に使われています。他のプロセス（開発サーバー等）を終了してから再試行してください。"
        )

    server = _start_server(8080)
    try:
        url = _build_authorize_url()
        if open_browser:
            webbrowser.open(url)

        deadline = time.time() + timeout_sec
        while _received_code is None and _received_error is None:
            if time.time() > deadline:
                raise RuntimeError(f"タイムアウト（{timeout_sec}秒）: 認可が完了しませんでした。")
            time.sleep(0.3)

        if _received_error:
            raise RuntimeError(f"認可エラー: {_received_error}")

        tokens = _exchange_code(_received_code, client_secret)

        token_manager.save({
            "client_secret": client_secret,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": int(time.time()) + tokens.get("expires_in", 3600),
        })

        # 連携確認。/me は存在しないため /office で事業者情報を取る。
        office_name = ""
        try:
            office = mf_client.get_office()
            block = office.get("data", office) if isinstance(office, dict) else {}
            attrs = block.get("attributes", {}) if isinstance(block, dict) else {}
            office_name = (
                block.get("name") or attrs.get("name")
                or block.get("office_name") or attrs.get("office_name") or ""
            )
            if office_name:
                token_manager.update(office_name=office_name)
        except Exception:
            pass

        return {
            "office_name": office_name,
            "authorize_url": url,
        }
    finally:
        server.shutdown()
