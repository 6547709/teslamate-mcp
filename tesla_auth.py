"""TeslaMate Owner API Token 读取与解密模块。

TeslaMate 使用 Elixir Cloak 库 (AES-256-GCM) 对存放在 `private.tokens` 表
中的 access/refresh token 进行加密存储。本模块负责：
  1. 从 private.tokens 表读取加密的 token（bytea 格式）
  2. 正确派生 32 字节 AES-256 解密密钥
  3. 按 Cloak V1 格式 (version || iv || ciphertext_with_tag) 解密

Cloak V1 二进制格式：
  - 第 0 字节   : 版本号 (固定 b'\x01')
  - 第 1-16 字节: 12 字节 Nonce (IV)
  - 第 17 字节起: ciphertext || 16 字节 auth tag (连在一起)
  - AAD (关联数据): b'AES.GCM.V1' (Cloak V1 固定值)

依赖 (已在 pyproject.toml 中声明):
  - cryptography>=42.0
  - psycopg2-binary>=2.9
"""

from __future__ import annotations

import base64
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
    """从 ENCRYPTION_KEY 派生符合 AES-256 要求的 32 字节密钥。

    TeslaMate 官方文档中 ENCRYPTION_KEY 通常是 Base64 编码的 32 字节随机串，
    但也可能直接是原始字符串。本函数按以下顺序尝试：

    1. 尝试 base64 解码：
       - 若解码后恰好得到 32 字节 → 直接返回（这是官方推荐格式）
       - 若不是 32 字节 → 将解码结果截断/补齐到 32 字节

    2. 若 base64 解码失败 → 将原始字符串以 UTF-8 编码，
       不足 32 字节尾部补 b'\x00'，超出则截断

    Args:
        raw_key: 环境变量 TESLA_ENCRYPTION_KEY 的原始值

    Returns:
        严格 32 字节的 AES-256 密钥
    """
    key_bytes: bytes

    # 尝试 base64 解码
    try:
        decoded = base64.b64decode(raw_key, validate=True)
        if len(decoded) == 32:
            key_bytes = decoded
        elif len(decoded) > 32:
            key_bytes = decoded[:32]      # 截断
        else:
            key_bytes = decoded + b'\x00' * (32 - len(decoded))  # 补齐
        logger.debug("ENCRYPTION_KEY: base64 解码成功，长度 %d 字节", len(key_bytes))
        return key_bytes
    except Exception:
        # base64 解码失败，按原始字符串处理
        pass

    # UTF-8 编码，不足补 \x00，超出截断
    key_bytes = raw_key.encode("utf-8")
    if len(key_bytes) < 32:
        key_bytes = key_bytes + b'\x00' * (32 - len(key_bytes))
    else:
        key_bytes = key_bytes[:32]
    logger.debug("ENCRYPTION_KEY: 使用 UTF-8 原始字符串处理，长度 %d 字节", len(key_bytes))
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

    本函数严格按照以下格式进行切片：
      - data[0:1]   → version（必须为 b'\x01'）
      - data[1:17]  → nonce (12 字节 IV)
      - data[17:]   → ciphertext || auth_tag（连在一起，共 n+16 字节）

    Python cryptography 的 AESGCM.decrypt() 可以直接接收 ciphertext+tag 的
    合并字节串，调用时将 associated_data 设为 b'AES.GCM.V1' 即可。

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

    iv = data[1:17]                        # 12 字节 Nonce
    ciphertext_with_tag = data[17:]         # ciphertext || 16 字节 auth tag

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
    """从 private.tokens 表读取并解密 access token。

    这是本模块的对外入口函数。它会：
      1. 检查缓存（避免频繁查库）
      2. 连接 TeslaMate 数据库查询 private.tokens 表
      3. 按 Cloak V1 格式解密 access token
      4. 缓存结果并返回

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

    # 派生 AES-256 密钥
    key = _derive_aes_key(ENCRYPTION_KEY)

    # 连接数据库读取 private.tokens 表
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # TeslaMate 将 token 存放在 private schema 的 tokens 表中
            # inserted_at 用于获取最新一条
            cur.execute(
                """
                SELECT access, refresh
                FROM private.tokens
                ORDER BY inserted_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("在 private.tokens 表中未找到任何 token 记录。")
            encrypted_access: bytes = row["access"]
            encrypted_refresh: bytes = row["refresh"]
    finally:
        conn.close()

    # 解密 access token
    if encrypted_access:
        try:
            _cached_access_token = _decrypt_cloak_v1(key, bytes(encrypted_access)).decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"access token 解密失败: {e}") from e
    else:
        _cached_access_token = ""

    # 解密 refresh token（备用）
    if encrypted_refresh:
        try:
            _cached_refresh_token = _decrypt_cloak_v1(key, bytes(encrypted_refresh)).decode("utf-8")
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
        # 触发完整加载
        get_decrypted_access_token()
    return _cached_refresh_token or ""
