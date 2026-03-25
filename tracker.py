#!/usr/bin/env python3
"""
中華郵政包裹追蹤器
支援 EB500100（國內郵件，免驗證碼）與 EB500200（國際/兩岸e小包，需驗證碼）
"""

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

import ddddocr
import requests

BASE_URL = "https://postserv.post.gov.tw/pstmail"
STATUS_FILE = Path(__file__).parent / "status.json"
MAX_RETRIES = 15

# EB500100: 國內郵件（免驗證碼）
# EB500200: 國際/兩岸e小包（需驗證碼）
TXNS = {
    "EB500100": {
        "InputVOClass": "com.systex.jbranch.app.server.post.vo.EB500100InputVO",
        "BizCode": "query2",
        "needs_captcha": False,
    },
    "EB500200": {
        "InputVOClass": "com.systex.jbranch.app.server.post.vo.EB500200InputVO",
        "BizCode": "query",
        "needs_captcha": True,
    },
}


def bark_notify(bark_key: str, title: str, body: str, group: str = "📦 包裹追蹤"):
    """透過 Bark 推播通知"""
    url = f"https://api.day.app/{bark_key}/{quote(title)}/{quote(body)}?group={quote(group)}"
    req = Request(url, method="GET")
    try:
        urlopen(req, timeout=10)
    except Exception as e:
        print(f"Bark 通知失敗: {e}")


def solve_captcha(session: requests.Session, ocr: ddddocr.DdddOcr) -> tuple[str, str]:
    """取得並辨識驗證碼，回傳 (uuid, captcha_text)"""
    captcha_uuid = str(uuid.uuid4())
    resp = session.get(f"{BASE_URL}/jcaptcha?uuid={captcha_uuid}")
    resp.raise_for_status()
    captcha_text = ocr.classification(resp.content)
    return captcha_uuid, captcha_text


def query(session: requests.Session, mail_no: str, txn_code: str,
          captcha_uuid: str = "", captcha_text: str = "") -> list:
    """查詢包裹追蹤資訊"""
    txn = TXNS[txn_code]
    payload = {
        "header": {
            "InputVOClass": txn["InputVOClass"],
            "TxnCode": txn_code,
            "BizCode": txn["BizCode"],
            "StampTime": True,
            "SupvPwd": "",
            "TXN_DATA": {},
            "SupvID": "",
            "CustID": "",
            "REQUEST_ID": "",
            "ClientTransaction": True,
            "DevMode": False,
            "SectionID": "esoaf",
        },
        "body": {
            "MAILNO": mail_no,
            "pageCount": 10,
        },
    }

    if txn["needs_captcha"]:
        payload["body"]["uuid"] = captcha_uuid
        payload["body"]["captcha"] = captcha_text

    resp = session.post(
        f"{BASE_URL}/EsoafDispatcher",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://postserv.post.gov.tw/pstmail/main_mail.html",
        },
    )
    resp.raise_for_status()
    return resp.json()


def fetch_tracking(session: requests.Session, mail_no: str, txn_code: str, ocr: ddddocr.DdddOcr) -> list[dict] | None:
    """取得追蹤紀錄，自動處理驗證碼重試"""
    txn = TXNS[txn_code]

    if not txn["needs_captcha"]:
        data = query(session, mail_no, txn_code)
        body = data[0]["body"]
        items = (body.get("host_rs") or {}).get("ITEM")
        if body.get("incorrectList"):
            print(f"  ⚠️  單號格式不符: {body['incorrectList']}")
            return None
        return items or []

    # 需要驗證碼，自動重試
    for attempt in range(1, MAX_RETRIES + 1):
        captcha_uuid, captcha_text = solve_captcha(session, ocr)
        print(f"  [{attempt}/{MAX_RETRIES}] OCR: {captcha_text}", end=" → ")

        data = query(session, mail_no, txn_code, captcha_uuid, captcha_text)
        body = data[0]["body"]

        if not body.get("cptCheck"):
            print("驗證碼錯誤")
            continue

        print("成功")
        return (body.get("host_rs") or {}).get("ITEM") or []

    print(f"  ❌ {MAX_RETRIES} 次辨識都失敗")
    return None


def fmt_dt(s: str) -> str:
    if len(s) >= 14:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}"
    return s


def fmt_date(s: str) -> str:
    """將 '20260325' 格式化為 '2026-03-25'"""
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def extract_details(item: dict) -> str:
    """從 ITEM 中提取詳細資訊（依 EVCODE 不同有不同欄位）"""
    evcode = item.get("EVCODE", "")
    details = []
    for key, val in item.items():
        if not key.endswith("-TITLE"):
            continue
        label = val.strip()
        if not label:
            continue
        # 對應的值欄位：先找 KEY（去 -TITLE），再找 KEY-{EVCODE}
        val_key = key.removesuffix("-TITLE")
        value = item.get(val_key, "").strip()
        if not value and evcode:
            value = item.get(f"{val_key}-{evcode}", "").strip()
        if value:
            details.append(f"{label}: {fmt_date(value)}")
    return " / ".join(details)


def fmt_item(item: dict) -> str:
    dt = fmt_dt(item.get("DATIME", ""))
    status = item.get("STATUS", "").strip()
    station = item.get("BRHNAT", item.get("BRHNC", "")).strip()
    nation = item.get("NATION-A", "").strip()
    loc = f"{station} ({nation})" if nation else station
    details = extract_details(item)
    line = f"{dt}  {status}  {loc}"
    if details:
        line += f"\n    {details}"
    return line


def load_status() -> dict:
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text("utf-8"))
    return {}


def save_status(status: dict):
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), "utf-8")


def is_international(mail_no: str) -> bool:
    """
    判斷是否為國際/兩岸郵件（EB500200），依中華郵政官方規則：
    - E 開頭 13 碼：國際快捷
    - R 開頭 13 碼：國際/大陸掛號
    - L 開頭 13 碼：國際e小包（LH = 兩岸e小包）
    - C 開頭 13 碼：國際/大陸包裹
    - EE/EZ 開頭 13 碼：大陸快捷
    - FT/FZ 開頭 13 碼：兩岸速遞(快捷)
    其餘視為國內郵件（EB500100）
    """
    if len(mail_no) == 13 and mail_no[:1] in ("E", "R", "L", "C", "F"):
        return True
    return False


def parse_mail_config(raw: str) -> list[dict]:
    """
    解析 MAIL_NO 環境變數，支援格式：
      單筆: LH038196094TW
      多筆: LH038196094TW,RR123456789TW
      指定類型: EB500200:LH038196094TW,EB500100:RR123456789TW
    未指定類型時依 13 碼英文開頭自動判斷國際/國內
    """
    entries = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            txn_code, mail_no = part.split(":", 1)
            entries.append({"mail_no": mail_no.strip().upper(), "txn_code": txn_code.strip().upper()})
        else:
            mail_no = part.upper()
            txn_code = "EB500200" if is_international(mail_no) else "EB500100"
            entries.append({"mail_no": mail_no, "txn_code": txn_code})
    return entries


def main():
    bark_key = os.environ.get("BARK_KEY", "")
    mail_no_raw = os.environ.get("MAIL_NO", "")

    if not mail_no_raw:
        print("錯誤: 請設定 MAIL_NO 環境變數")
        sys.exit(1)

    entries = parse_mail_config(mail_no_raw)
    if not entries:
        print("錯誤: MAIL_NO 解析結果為空")
        sys.exit(1)

    print(f"共 {len(entries)} 筆追蹤單號")
    status = load_status()
    session = requests.Session()
    session.get(f"{BASE_URL}/assets/txn/EB500200/EB500200.html")
    session.get(f"{BASE_URL}/SessionServlet")

    # 只在有需要驗證碼的單號時才初始化 OCR
    needs_ocr = any(TXNS[e["txn_code"]]["needs_captcha"] for e in entries)
    ocr = ddddocr.DdddOcr(show_ad=False) if needs_ocr else None

    has_update = False

    for entry in entries:
        mail_no = entry["mail_no"]
        txn_code = entry["txn_code"]
        print(f"\n📦 {mail_no} ({txn_code})")

        items = fetch_tracking(session, mail_no, txn_code, ocr)
        if items is None:
            continue

        # 格式化紀錄
        records = [fmt_item(item) for item in items]
        prev_count = len(status.get(mail_no, {}).get("records", []))
        curr_count = len(records)

        if curr_count > prev_count:
            new_records = records[:curr_count - prev_count]
            print(f"  🆕 新增 {len(new_records)} 筆紀錄:")
            for r in new_records:
                print(f"    {r}")

            # Bark 通知
            if bark_key:
                latest = new_records[0]
                bark_notify(
                    bark_key,
                    f"📦 {mail_no}",
                    latest,
                )

            status[mail_no] = {"txn_code": txn_code, "records": records}
            has_update = True
        else:
            print(f"  無新進度（共 {curr_count} 筆紀錄）")

    if has_update:
        save_status(status)
        print("\n✅ 狀態已更新")
    else:
        print("\n無任何更新")


if __name__ == "__main__":
    main()
