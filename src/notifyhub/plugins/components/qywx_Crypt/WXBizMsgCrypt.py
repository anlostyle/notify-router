import base64
import hashlib
import secrets
import struct
import time
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import ierror


def _signature(token, timestamp, nonce, encrypted):
    return hashlib.sha1("".join(sorted([token, str(timestamp), str(nonce), encrypted])).encode()).hexdigest()


def _pad(data):
    size = 32 - len(data) % 32
    return data + bytes([size]) * size


def _unpad(data):
    if not data:
        raise ValueError("empty buffer")
    size = data[-1]
    if size < 1 or size > 32 or data[-size:] != bytes([size]) * size:
        raise ValueError("invalid padding")
    return data[:-size]


class WXBizMsgCrypt:
    def __init__(self, token, encoding_aes_key, receive_id):
        self.token = str(token)
        self.receive_id = str(receive_id)
        try:
            self.key = base64.b64decode(str(encoding_aes_key) + "=")
        except Exception as exc:
            raise ValueError("invalid EncodingAESKey") from exc
        if len(self.key) != 32:
            raise ValueError("invalid EncodingAESKey")

    def _decrypt(self, encrypted):
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).decryptor()
        raw = _unpad(cipher.update(base64.b64decode(encrypted)) + cipher.finalize())
        length = struct.unpack("!I", raw[16:20])[0]
        message = raw[20 : 20 + length]
        receive_id = raw[20 + length :].decode()
        if receive_id != self.receive_id:
            raise ValueError("receive id mismatch")
        return message

    def _encrypt(self, message):
        body = message.encode() if isinstance(message, str) else bytes(message)
        raw = secrets.token_bytes(16) + struct.pack("!I", len(body)) + body + self.receive_id.encode()
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).encryptor()
        return base64.b64encode(cipher.update(_pad(raw)) + cipher.finalize()).decode()

    def VerifyURL(self, msg_signature, timestamp, nonce, echo_str):
        if _signature(self.token, timestamp, nonce, echo_str) != msg_signature:
            return ierror.WXBizMsgCrypt_ValidateSignature_Error, None
        try:
            return ierror.WXBizMsgCrypt_OK, self._decrypt(echo_str)
        except ValueError as exc:
            if "receive id" in str(exc):
                return ierror.WXBizMsgCrypt_ValidateCorpid_Error, None
            return ierror.WXBizMsgCrypt_DecryptAES_Error, None

    def DecryptMsg(self, post_data, msg_signature, timestamp, nonce):
        try:
            root = ET.fromstring(post_data)
            encrypted = root.findtext("Encrypt") or ""
        except (ET.ParseError, TypeError):
            return ierror.WXBizMsgCrypt_ParseXml_Error, None
        if _signature(self.token, timestamp, nonce, encrypted) != msg_signature:
            return ierror.WXBizMsgCrypt_ValidateSignature_Error, None
        try:
            return ierror.WXBizMsgCrypt_OK, self._decrypt(encrypted)
        except ValueError as exc:
            if "receive id" in str(exc):
                return ierror.WXBizMsgCrypt_ValidateCorpid_Error, None
            return ierror.WXBizMsgCrypt_DecryptAES_Error, None

    def EncryptMsg(self, reply_msg, nonce, timestamp=None):
        timestamp = str(timestamp or int(time.time()))
        try:
            encrypted = self._encrypt(reply_msg)
            signature = _signature(self.token, timestamp, nonce, encrypted)
            xml = (
                "<xml>"
                f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
                f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
                f"<TimeStamp>{timestamp}</TimeStamp>"
                f"<Nonce><![CDATA[{nonce}]]></Nonce>"
                "</xml>"
            )
            return ierror.WXBizMsgCrypt_OK, xml
        except Exception:
            return ierror.WXBizMsgCrypt_EncryptAES_Error, None
