#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot probe: what does this account really require when saving a customer?

It is the **"试推 → 回读 → 删除"** step of the SOP (§7) made executable.  It
creates a ``ZZ-TEST-*`` customer, prints the raw answer, reads it back and then
deletes it — so the question "元数据标了必录，WebAPI 真的会拦吗？" is answered by the
account instead of by trial and error inside Odoo.

The customer is saved **without** ``FTTel`` and without the contact sub-entity
(``FT_BD_CUSTCONTACT``): the account metadata marks ``FTTel`` as mandatory, but
all 349 customers in the account have it empty, so the flag alone is not proof.

It talks to the account directly through the WebAPI SDK, so Odoo is not needed.
Credentials come from the environment, with the same names the MCP server uses::

    KD_SERVER_URL  KD_ACCT_ID  KD_USERNAME  KD_APP_ID  KD_APP_SEC
    KD_LCID (default 2052)   KD_ORG_NUM (default 0)

Usage::

    python tools/try_save_customer.py             # create, read back, delete
    python tools/try_save_customer.py --keep      # leave the record behind

Safety: the number must start with ``ZZ-TEST`` (refused otherwise) and the
record is deleted at the end unless ``--keep`` is given, so an interrupted run
still leaves an obviously temporary record.
"""

import argparse
import json
import os
import sys
import time

FORM_ID = "BD_Customer"
PREFIX = "ZZ-TEST"

# Values read from the account itself (see README: Kingdee reference values).
ORG = "100"                      # FCreateOrgId / FUseOrgId
CURRENCY = "PRE001"              # FTRADINGCURRID, 人民币
SALESMAN = "000_XS2001_1"        # FSELLER, BD_Saler
SALES_DEPT = "ZN0802"            # FSALDEPTID, BD_Department (销售类部门)


def make_sdk():
    try:
        from k3cloud_webapi_sdk.main import K3CloudApiSdk
    except ImportError as err:
        sys.exit(
            "k3cloud_webapi_sdk is not installed for this interpreter (%s).\n"
            "Install the wheel shipped with the module, then retry." % err)

    url = (os.environ.get("KD_SERVER_URL") or "").strip()
    missing = [k for k in ("KD_SERVER_URL", "KD_ACCT_ID", "KD_USERNAME",
                           "KD_APP_ID", "KD_APP_SEC") if not (os.environ.get(k) or "").strip()]
    if missing:
        sys.exit("missing environment variables: %s" % ", ".join(missing))

    api = K3CloudApiSdk(url)
    api.InitConfig(
        os.environ["KD_ACCT_ID"].strip(),
        os.environ["KD_USERNAME"].strip(),
        os.environ["KD_APP_ID"].strip(),
        os.environ["KD_APP_SEC"].strip(),
        url,
        lcid=int(os.environ.get("KD_LCID") or 2052),
        org_num=int(os.environ.get("KD_ORG_NUM") or 0),
    )
    return api


def decode(raw):
    if isinstance(raw, BaseException):
        return None, str(raw)
    if not isinstance(raw, str):
        return None, "unexpected %s" % type(raw).__name__
    try:
        return json.loads(raw), None
    except ValueError:
        return None, (raw or "").strip()[:400] or "empty answer"


def report(label, raw):
    """Print the readable outcome of one call; return (success, payload)."""
    payload, error = decode(raw)
    if error is not None:
        print("%s: FAILED to decode -> %s" % (label, error))
        return False, {}
    result = payload.get("Result") if isinstance(payload, dict) else None
    status = result.get("ResponseStatus") if isinstance(result, dict) else None
    if not isinstance(status, dict):
        print("%s: no ResponseStatus (payload=%s)" % (label, json.dumps(payload, ensure_ascii=False)[:300]))
        return False, payload
    success = str(status.get("IsSuccess") or "").strip().lower() == "true"
    print("%s: IsSuccess=%s   MsgCode=%s" % (label, success, status.get("MsgCode")))
    if status.get("Message"):
        print("   Message : %s" % status["Message"])
    errors = status.get("Errors")
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, dict) and (err.get("Message") or err.get("FieldName")):
                print("   Error   : %s   (FieldName=%s)" % (
                    err.get("Message"), err.get("FieldName") or "-"))
    return success, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true",
                        help="do not delete the record at the end")
    parser.add_argument("--number", help="explicit number (must start with ZZ-TEST)")
    args = parser.parse_args()

    number = (args.number or "").strip() or "%s-CUST-%s" % (PREFIX, time.strftime("%m%d%H%M%S"))
    if not number.startswith(PREFIX):
        sys.exit("refused: the number must start with %r so the record is "
                 "recognisable in the account (got %r)" % (PREFIX, number))

    api = make_sdk()

    model = {
        "FCreateOrgId": {"FNumber": ORG},
        "FUseOrgId": {"FNumber": ORG},
        "FNumber": number,
        "FName": "ZZ-TEST 临时验证客户（可删除）",
        "FTRADINGCURRID": {"FNumber": CURRENCY},
        "FSELLER": {"FNumber": SALESMAN},
        "FSALDEPTID": {"FNumber": SALES_DEPT},
        # 刻意不含 FTTel，也不含联系人子实体 FT_BD_CUSTCONTACT
    }
    save_payload = {
        "NeedUpDateFields": [],
        "NeedReturnFields": [],
        "IsDeleteEntry": "True",
        "SubSystemId": "",
        "IsVerifyBaseDataField": "False",
        "IsEntryBatchFill": "True",
        "ValidateFlag": "True",
        "NumberSearch": "True",
        "IsAutoAdjustField": "False",
        "InterationFlags": "",
        "IgnoreInterationFlag": "",
        "IsControlPrecision": "False",
        "Model": model,
    }

    print("form    : %s" % FORM_ID)
    print("number  : %s" % number)
    print("sent    : %s" % ", ".join(sorted(model)))
    print("omitted : FTTel, FT_BD_CUSTCONTACT (联系人子实体)")
    print()

    print("[1/3] Save（不带 FTTel）...")
    success, _ = report("Save", api.Save(FORM_ID, save_payload))
    print()

    if success:
        print(">>> 结论：不传 FTTel 也能创建成功 —— FTTel 不是 WebAPI 的强制字段")
        print()
        print("[2/3] View 回读...")
        report("View", api.View(FORM_ID, {
            "CreateOrgId": 0, "Number": number, "Id": "", "IsSortBySeq": "false",
        }))
    else:
        print(">>> 结论：创建被拒 —— 看上面的 MsgCode / Error 判断是哪一项（若指向 FTTel 则它确为强制）")

    print()
    if args.keep:
        print("[3/3] 跳过删除（--keep）。请手工清理金蝶里的 %s" % number)
        return 0
    if not success:
        print("[3/3] 无需删除（未创建成功）")
        return 0

    print("[3/3] Delete 清理...")
    report("Delete", api.Delete(FORM_ID, {
        "CreateOrgId": 0, "Numbers": [number], "Ids": "",
        "SelectedPostId": 0, "NetworkCtrl": "", "IgnoreInterationFlag": "",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
