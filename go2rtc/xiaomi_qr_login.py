"""Xiaomi QR-code login (scan with Mi Home app) -> write userId/passToken into go2rtc.yaml.

Avoids the SMS 2FA path that go2rtc's password login cannot complete.
Flow adapted from PiotrMachowski/Xiaomi-cloud-tokens-extractor (QrCodeXiaomiCloudConnector).
Secrets are never printed; only lengths and pass/fail are reported.
"""
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
CONFIG = Path(os.environ.get("GO2RTC_CONFIG", HERE / "go2rtc.yaml"))
QR_FILE = CONFIG.parent / "xiaomi_qr.png"
SID = "xiaomiio"
# Server holds the long-poll >70s; a short client timeout drops the socket and the
# scan result can be delivered to the dead connection, so keep the request open.
POLL_TIMEOUT_S = 120

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("qr_login")


def parse(text: str) -> dict:
    return json.loads(text.removeprefix("&&&START&&&"))


def get_qr(s: requests.Session) -> dict:
    res = s.get("https://account.xiaomi.com/longPolling/loginUrl", params={
        "_qrsize": "480",
        "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
        "callback": "https://sts.api.io.mi.com/sts",
        "_hasLogo": "false",
        "sid": SID,
        "serviceParam": "",
        "_locale": "zh_CN",
        "_dc": str(int(time.time() * 1000)),
    }, timeout=15)
    res.raise_for_status()
    return parse(res.text)


def wait_scan(s: requests.Session, lp_url: str, timeout_s: int) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            res = s.get(lp_url, timeout=POLL_TIMEOUT_S)
        except requests.exceptions.Timeout:
            continue
        log.info("poll status %s", res.status_code)
        if res.status_code == 200:
            return parse(res.text)
        time.sleep(2)
    raise TimeoutError("QR code not scanned in time")


def check_token_like_go2rtc(user_id: str, pass_token: str) -> bool:
    """Replay go2rtc's LoginWithToken: serviceLogin with only userId+passToken cookies."""
    res = requests.get(
        f"https://account.xiaomi.com/pass/serviceLogin?_json=true&sid={SID}",
        headers={"Cookie": f"userId={user_id}; passToken={pass_token}"},
        timeout=15,
    )
    v = parse(res.text)
    ok = bool(v.get("location")) and bool(v.get("ssecurity"))
    log.info("go2rtc-style token check: %s (code=%s)", "OK" if ok else "FAIL", v.get("code"))
    return ok


def write_config(user_id: str, pass_token: str) -> None:
    text = CONFIG.read_text()
    text = re.sub(r"\nxiaomi:\n(  .*\n?)*", "\n", text)
    text = text.rstrip("\n") + f'\nxiaomi:\n  "{user_id}": "{pass_token}"\n'
    CONFIG.write_text(text)
    CONFIG.chmod(0o600)


def main() -> int:
    s = requests.Session()
    qr = get_qr(s)
    QR_FILE.write_bytes(s.get(qr["qr"], timeout=15).content)
    subprocess.run(["open", "-a", "Preview", str(QR_FILE)], check=False)
    subprocess.run(["osascript", "-e", 'tell application "Preview" to activate'], check=False)
    log.info("请用米家 App 扫码（我的 → 右上角扫一扫），%ss 内有效", qr["timeout"])

    data = wait_scan(s, qr["lp"], int(qr["timeout"]))
    QR_FILE.unlink(missing_ok=True)
    user_id, pass_token = str(data["userId"]), data["passToken"]
    log.info("scan OK: userId=%s passToken len=%d", user_id, len(pass_token))

    if not check_token_like_go2rtc(user_id, pass_token):
        log.error("token not accepted by go2rtc-style login; config not changed")
        return 1
    write_config(user_id, pass_token)
    log.info("written to %s", CONFIG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
