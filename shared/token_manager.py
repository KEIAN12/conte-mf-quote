"""macOS Keychain でMF OAuthトークンを管理するモジュール

保存する情報:
- client_secret: MF Client Secret（ユーザー入力）
- access_token: アクセストークン
- refresh_token: リフレッシュトークン
- expires_at: アクセストークン失効時刻（UNIX timestamp）
- user_email: 連携しているMFユーザー（認証時に取得）

Keychainには全部まとめてJSON文字列として保存。
"""

import json
import subprocess
import time
from typing import Optional
from config import KEYCHAIN_SERVICE, TOKEN_URL, CLIENT_ID


def _get_raw() -> Optional[str]:
    """Keychainからraw文字列を取得（存在しなければNone）"""
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE,
             "-a", "default",
             "-w"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _set_raw(value: str) -> None:
    """Keychainに保存（既存があれば上書き）"""
    # 既存エントリを削除（存在しなくてもエラーにしない）
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", KEYCHAIN_SERVICE,
         "-a", "default"],
        capture_output=True
    )
    # 新しく追加
    subprocess.run(
        ["security", "add-generic-password",
         "-s", KEYCHAIN_SERVICE,
         "-a", "default",
         "-w", value,
         "-U"],
        check=True, capture_output=True
    )


def load() -> dict:
    """保存されている全情報を読み出す（なければ空dict）"""
    raw = _get_raw()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def save(data: dict) -> None:
    """全情報を上書き保存"""
    _set_raw(json.dumps(data, ensure_ascii=False))


def update(**kwargs) -> dict:
    """一部フィールドだけ更新"""
    data = load()
    data.update(kwargs)
    save(data)
    return data


def clear() -> None:
    """保存情報を全削除（連携解除用）"""
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", KEYCHAIN_SERVICE,
         "-a", "default"],
        capture_output=True
    )


def get_access_token() -> str:
    """有効なアクセストークンを返す。期限切れなら自動リフレッシュ。

    Returns:
        access_token文字列

    Raises:
        RuntimeError: 保存情報がない、または更新失敗時
    """
    data = load()
    if not data.get("access_token"):
        raise RuntimeError(
            "MFトークンが保存されていません。まず `mf-setup` で初回セットアップをしてください。"
        )

    # 期限チェック（5分のバッファ付き）
    expires_at = data.get("expires_at", 0)
    if time.time() + 300 < expires_at:
        return data["access_token"]

    # リフレッシュ
    return refresh_access_token()


def refresh_access_token() -> str:
    """リフレッシュトークンで新しいアクセストークンを取得

    Returns:
        新しいaccess_token

    Raises:
        RuntimeError: リフレッシュ失敗時
    """
    import urllib.request
    import urllib.parse
    import base64

    data = load()
    refresh_token = data.get("refresh_token")
    client_secret = data.get("client_secret")
    if not refresh_token or not client_secret:
        raise RuntimeError(
            "リフレッシュトークンまたはClient Secretがありません。"
            "`mf-setup` で再セットアップしてください。"
        )

    # CLIENT_SECRET_BASIC方式（Authorizationヘッダ）
    creds = f"{CLIENT_ID}:{client_secret}".encode()
    auth = base64.b64encode(creds).decode()

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f"トークンリフレッシュ失敗: {e}")

    # 保存
    update(
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token", refresh_token),
        expires_at=int(time.time()) + tok.get("expires_in", 3600),
    )

    return tok["access_token"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: token_manager.py [show|clear|refresh]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "show":
        d = load()
        if not d:
            print("（保存情報なし）")
        else:
            # トークンはマスク
            masked = {
                **d,
                "access_token": (d.get("access_token", "")[:10] + "...") if d.get("access_token") else None,
                "refresh_token": (d.get("refresh_token", "")[:10] + "...") if d.get("refresh_token") else None,
                "client_secret": "***" if d.get("client_secret") else None,
            }
            print(json.dumps(masked, indent=2, ensure_ascii=False))
    elif cmd == "clear":
        clear()
        print("削除しました")
    elif cmd == "refresh":
        print(refresh_access_token()[:20] + "...")
    else:
        print(f"不明なコマンド: {cmd}")
        sys.exit(1)
