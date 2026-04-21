"""CONTE MF Quote プラグインの設定値

Client IDは株式会社CONTEのMF Developer Portalで発行したclaude-agentアプリのもの。
Client Secretはユーザー（社員）が初回セットアップ時に入力し、macOS Keychainに保存される。
"""

# MF Developer Portal「claude-agent」アプリのClient ID
# （Client Secretはプラグインに埋め込まず、Keychain管理）
CLIENT_ID = "238122083351420"

# OAuthで要求するスコープ（見積・請求書の読み書きのみ、最小権限）
SCOPES = "mfc/invoice/data.read mfc/invoice/data.write"

# ローカルコールバック（MF Developer Portal設定と一致させる必要あり）
REDIRECT_URI = "http://localhost:8080/callback"

# MF OAuthエンドポイント
AUTHORIZE_URL = "https://api.biz.moneyforward.com/authorize"
TOKEN_URL = "https://api.biz.moneyforward.com/token"

# MF Invoice API v3 ベースURL
API_BASE = "https://invoice.moneyforward.com/api/v3"

# Keychainサービス名（トークン保存のキー）
KEYCHAIN_SERVICE = "conte-mf-quote"

# 有効期限のデフォルト日数
DEFAULT_EXPIRE_DAYS = 30

# 税率（固定10%）
DEFAULT_TAX_RATE = "ten_percent"
