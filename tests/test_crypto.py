import xml.etree.ElementTree as ET

from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt


def test_wecom_crypto_round_trip():
    crypt = WXBizMsgCrypt("token", "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG", "corp")
    code, encrypted_xml = crypt.EncryptMsg("<xml><Content>test</Content></xml>", "nonce", "1700000000")
    assert code == 0
    root = ET.fromstring(encrypted_xml)
    code, plain = crypt.DecryptMsg(
        f"<xml><Encrypt><![CDATA[{root.findtext('Encrypt')}]]></Encrypt></xml>",
        root.findtext("MsgSignature"),
        root.findtext("TimeStamp"),
        root.findtext("Nonce"),
    )
    assert code == 0
    assert plain == b"<xml><Content>test</Content></xml>"
