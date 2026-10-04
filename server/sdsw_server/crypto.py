"""Cryptography of the game's NEX library (OnlineCore / RendezVousCommon), reimplemented.

  RC4                  nn::nex::RC4Encryption: a key of length 0 leaves the data unchanged, which is what the
                       authentication connection uses (no session key yet)
  Kerberos encryption  KerberosEncryption::Encrypt: RC4(key) then HMAC-MD5(key, ciphertext) appended
  User key             MD5KeyDerivation::CreateKey: MD5 applied 65000 + pid % 1024 times to the password
                       (constants set by the RendezVousCommon static initialiser)
"""

from __future__ import annotations

import hashlib
import hmac


class RC4:
    """RC4 keeping its state between calls (one per direction and substream)."""

    def __init__(self, key: bytes) -> None:
        self.key = bytes(key)
        s = list(range(256))
        if key:
            j = 0
            for i in range(256):
                j = (j + s[i] + key[i % len(key)]) & 0xFF
                s[i], s[j] = s[j], s[i]
        self.s = s
        self.i = self.j = 0

    def crypt(self, data: bytes) -> bytes:
        if not self.key:
            return bytes(data)
        s, i, j = self.s, self.i, self.j
        out = bytearray(len(data))
        for n, b in enumerate(data):
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            out[n] = b ^ s[(s[i] + s[j]) & 0xFF]
        self.i, self.j = i, j
        return bytes(out)


def hmac_md5(key: bytes, *parts: bytes) -> bytes:
    mac = hmac.new(key, digestmod=hashlib.md5)
    for p in parts:
        mac.update(p)
    return mac.digest()


def derive_user_key(pid: int, password: str | bytes) -> bytes:
    data = password.encode("ascii") if isinstance(password, str) else password
    for _ in range(65000 + pid % 1024):
        data = hashlib.md5(data).digest()
    return data


class KerberosError(Exception):
    pass


def kerberos_encrypt(key: bytes, data: bytes) -> bytes:
    enc = RC4(key).crypt(data)
    return enc + hmac_md5(key, enc)


def kerberos_decrypt(key: bytes, data: bytes) -> bytes:
    if len(data) < 16:
        raise KerberosError("encrypted data too short")
    enc, mac = data[:-16], data[-16:]
    if not hmac.compare_digest(hmac_md5(key, enc), mac):
        raise KerberosError("bad HMAC (wrong key)")
    return RC4(key).crypt(enc)
