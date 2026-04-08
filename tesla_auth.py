"""TeslaMate Owner API Token 读取与解密模块。

TeslaMate 使用 Elixir Cloak 库 (AES-256-GCM) 对存放在 `public.tokens` 表
中的 access/refresh token 进行加密存储。本模块负责：
  1. 从 public.tokens 表读取加密的 token（bytea 格式）
  2. 正确派生 32 字节 AES-256 解密密钥（SHA256 哈希）
  3. 按 Cloak V1 格式 (version || iv || ciphertext_with_tag) 解密

密钥派生（来自 TeslaMate 源码 vault.ex）：
  AES_key = SHA256(ENCRYPTION_KEY as UTF-8 bytes)

Cloak V1 二进制格式：
  - 第 0 字节   : 版本号 (固定 b'\x01')
  - 第 1-12 字节: 12 字节 Nonce (IV)
  - 第 13 字节起: ciphertext || 16 字节 auth tag (连在一起)
  - AAD (关联数据): b'AES.GCM.V1' (Cloak V1 固定值)

依赖 (已在 pyproject.toml 中声明):
  - cryptography>=42.0
  - psycopg2-binary>=2.9
"""

from __future__ import annotations

import hashlib
import os
import logging

import psycopg2
import psycopg2.extras
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

DB_HOST: str = os.environ.get("TESLAMATE_DB_HOST", "")
DB_PORT: int = int(os.environ.get("TESLAMATE_DB_PORT", "5432"))
DB_USER: str = os.environ.get("TESLAMATE_DB_USER", "teslamate")
DB_PASS: str = os.environ.get("TESLAMATE_DB_PASS", "")
DB_NAME: str = os.environ.get("TESLAMATE_DB_NAME", "teslamate")
ENCRYPTION_KEY: str = os.environ.get("ENCRYPTION_KEY", "")

HAS_TESLAMATE: bool = bool(DB_HOST and DB_PASS)

# Cloak V1 固定关联数据（AAD）
CLOAK_V1_AAD: bytes = b"AES.GCM.V1"

# ---------------------------------------------------------------------------
# 密钥处理
# ---------------------------------------------------------------------------

def _derive_aes_key(raw_key: str) -> bytes:
    """从 ENCRYPTION_KEY 派生 AES-256 密钥。

    TeslaMate 的 vault.ex 源码：
        setup_vault(key) ->
          default_cipher(:crypto.hash(:sha256, key))
          即：AES_key = SHA256(key)

    其中 key 是从环境变量或文件读取的原始字符串：
      - 如果是 TeslaMate 自动生成的密钥：是 48 字节随机数的 Base64 编码
        (无 padding，64 字符)，需要先 base64_decode 再 SHA256
      - 如果是用户自定义明文字符串：直接 SHA256

    本函数复现完全相同的派生逻辑。

    Args:
        raw_key: 环境变量 TESLA_ENCRYPTION_KEY 的原始值

    Returns:
        严格 32 字节的 AES-256 密钥
    """
    import base64 as b64

    try:
        decoded = b64.b64decode(raw_key, validate=True)
        if len(decoded) == 48:
            # TeslaMate 生成的 48 字节随机密钥：base64_decode → SHA256
            key_bytes = hashlib.sha256(decoded).digest()
            logger.debug(
                "ENCRYPTION_KEY: TeslaMate 生成格式 (48B随机数 base64编码)，"
                "SHA256 后得到 %d 字节 AES 密钥", len(key_bytes)
            )
            return key_bytes
    except Exception:
        pass

    # 用户自定义明文字符串：直接 SHA256
    key_bytes = hashlib.sha256(raw_key.encode("utf-8")).digest()
    logger.debug(
        "ENCRYPTION_KEY: 自定义明文字符串，直接 SHA256 后得到 %d 字节 AES 密钥",
        len(key_bytes)
    )
    return key_bytes


# ---------------------------------------------------------------------------
# 数据库连接
# ---------------------------------------------------------------------------

def _get_conn():
    """建立到 TeslaMate PostgreSQL 数据库的连接。"""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )


# ---------------------------------------------------------------------------
# 核心解密逻辑 (Cloak V1)
# ---------------------------------------------------------------------------

def _decrypt_cloak_v1(key: bytes, data: bytes) -> bytes:
    """按 Cloak V1 格式解密 token。

    TeslaMate 使用 Cloak 的 AES-256-GCM 模式加密 token。Cloak V1 将
    加密结果拼接为: version || iv || ciphertext || auth_tag，
    其中 auth_tag 固定 16 字节，位于密文尾部。

    二进制布局（Cloak.Vault 文档注释）：
      +--------+--------+--------+--------+
      | version |   IV (12B)  | ciphertext+tag |
      +--------+--------+--------+--------+
      |  1B   |    12B        |    n+16B       |

    Python AESGCM.decrypt() 直接接收 ciphertext+tag 合并字节串，
    并将 associated_data 设为 b'AES.GCM.V1'。

    Args:
        key:  32 字节 AES-256 密钥
        data: 原始加密数据（bytes，来自 PostgreSQL bytea 列）

    Returns:
        解密后的明文字节串

    Raises:
        ValueError: version 字节不是 b'\x01'
        Exception:  解密失败（密钥错误或数据被篡改）
    """
    if len(data) < 18:
        raise ValueError(f"Cloak V1 数据太短（至少需要 18 字节，实际 {len(data)} 字节）")

    version = data[0:1]
    if version != b'\x01':
        raise ValueError(f"未知的 Cloak 版本号: {version!r}，仅支持 V1 (b'\\x01')")

    iv = data[1:13]                          # 12 字节 Nonce
    ciphertext_with_tag = data[13:]           # ciphertext || 16 字节 auth tag

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(
        nonce=iv,
        data=ciphertext_with_tag,
        associated_data=CLOAK_V1_AAD,
    )
    return plaintext


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

_cached_access_token: str | None = None
_cached_refresh_token: str | None = None


def get_decrypted_access_token() -> str:
    """从 public.tokens 表读取并解密 access token。

    TeslaMate 的 Ecto Migration 将加密后的 token 字段 rename 为
    'access' 和 'refresh'，存放在 public schema 的 tokens 表中。
    这是本模块的对外入口函数。

    Returns:
        解密后的 access token 字符串（Bearer Token）

    Raises:
        RuntimeError: 数据库未配置或未找到 token 记录
        Exception:  解密失败（通常是 ENCRYPTION_KEY 不正确）
    """
    global _cached_access_token, _cached_refresh_token

    if _cached_access_token:
        return _cached_access_token

    if not HAS_TESLAMATE:
        raise RuntimeError(
            "TeslaMate 数据库未配置。"
            "请设置 TESLAMATE_DB_HOST、TESLAMATE_DB_PASS 环境变量。"
        )

    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY 环境变量未设置。"
            "请设置与 TeslaMate 相同的加密密钥。"
        )

    # 派生 AES-256 密钥：SHA256(ENCRYPTION_KEY)，与 TeslaMate Elixir 端一致
    key = _derive_aes_key(ENCRYPTION_KEY)

    # 连接数据库读取 public.tokens 表（注意是 public.tokens，不是 private.tokens）
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT access, refresh
                FROM tokens
                ORDER BY inserted_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("在 tokens 表中未找到任何 token 记录。")
            encrypted_access = row["access"]
            encrypted_refresh = row["refresh"]
    finally:
        conn.close()

    # 解密 access token
    if encrypted_access:
        try:
            _cached_access_token = _decrypt_cloak_v1(
                key, bytes(encrypted_access)
            ).decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"access token 解密失败: {e}") from e
    else:
        _cached_access_token = ""

    # 解密 refresh token（备用）
    if encrypted_refresh:
        try:
            _cached_refresh_token = _decrypt_cloak_v1(
                key, bytes(encrypted_refresh)
            ).decode("utf-8")
        except Exception as e:
            logger.warning("refresh token 解密失败（不影响主流程）: %s", e)
            _cached_refresh_token = ""

    logger.info("Token 解密成功")
    return _cached_access_token


def clear_token_cache() -> None:
    """清除内存中的 token 缓存，强制下次重新读取并解密。

    当 token 过期需要刷新时调用此函数。
    """
    global _cached_access_token, _cached_refresh_token
    _cached_access_token = None
    _cached_refresh_token = None
    logger.debug("Token 缓存已清除")


def get_decrypted_refresh_token() -> str:
    """获取解密后的 refresh token。"""
    global _cached_refresh_token
    if not _cached_refresh_token:
        get_decrypted_access_token()
    return _cached_refresh_token or ""
