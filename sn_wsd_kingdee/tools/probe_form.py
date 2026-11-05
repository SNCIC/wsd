#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print the mapping material of a Kingdee business object (offline, read-only).

Reads the **authoritative field master index** of the knowledge base
(``fields_master.csv``) and prints, for one ``formId``:

* the entity list, with its field count,
* every field the **account** marks as mandatory, with its entity, the base data
  object it references and its enum values,
* a payload skeleton nested per entity, ready to adapt in ``_kingdee_payload()``.

Why the master index and not the platform tree
----------------------------------------------
``fields_master.csv`` merges the **account** metadata (``live_metadata/``) over
the platform registration (``metadata/``); the two disagree on a few fields.
On ``BD_Customer`` the platform marks ``FName`` / ``FCreateOrgId`` /
``FTRADINGCURRID`` and the account *also* marks ``FSELLER`` / ``FSALDEPTID`` /
``FTTel``.  Reading the platform tree alone therefore **under-reports what the
account refuses** — the account only tells you when the Save is rejected.
``--legacy`` falls back to ``metadata/{formId}.json`` when the master index is
not available (it then prints a warning).

Usage::

    python tools/probe_form.py BD_Customer
    python tools/probe_form.py BD_Customer --find 币别
    python tools/probe_form.py BD_MATERIAL --all

The knowledge base path defaults to the local harvest; override it with
``--kb`` or the ``KINGDEE_KB`` environment variable.
"""

import argparse
import collections
import csv
import io
import json
import os
import sys

DEFAULT_KB = os.environ.get("KINGDEE_KB", r"D:/odoo/odoo-kingdee/data/kingdee-openapi")
MASTER_FILE = "fields_master.csv"

# Only used by --legacy (platform tree): fieldType is a Kingdee internal code,
# these are the ones identified from the statistical profile of the field index.
TYPE_HINT = {
    1: "Char", 13: "Many2one", 8: "Boolean", 9: "Selection", 21: "Float(金额)",
    4: "Date", 22: "Float(数量)", 2: "Float(率)", 40: "Selection",
    18: "Many2one(SEC_User)", 36: "Char", 7: "Many2one(组织)", 26: "Datetime",
    28: "Datetime", 6: "Text", 20: "Float(单价)", 3: "Integer",
}

HEADER_ENTITIES = ("FBillHead", "")


# ----------------------------------------------------------------------
# Master index (account-first) — the default source
# ----------------------------------------------------------------------
def load_master(kb, form_id):
    """Return the field rows of ``form_id`` from the master index, or None."""
    path = os.path.join(kb, MASTER_FILE)
    if not os.path.isfile(path):
        return None
    rows = []
    with io.open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("formId") or "") == form_id:
                rows.append(row)
    return rows or None


def placeholder(odoo_type, lookup):
    """Sample value for the payload skeleton, from the inferred Odoo type."""
    if lookup:
        return {"FNumber": "..."}
    if odoo_type == "Boolean":
        return "False"
    if odoo_type in ("Float", "Integer"):
        return 0
    if odoo_type in ("Date", "Datetime"):
        return "2026-01-01"
    return "..."


def skeleton_from_master(rows):
    """Payload skeleton of the mandatory fields: header flat, entities nested."""
    payload = {}
    for row in rows:
        if row.get("必录") != "Y":
            continue
        key = row.get("字段key")
        if not key:
            continue
        value = placeholder(row.get("Odoo类型") or "", row.get("引用对象") or "")
        entity = row.get("实体") or ""
        if entity in HEADER_ENTITIES:
            payload.setdefault(key, value)
        else:
            payload.setdefault(entity, {})[key] = value
    return payload


def render_master(rows, args):
    """Print the report of one formId from the master index."""
    print("%s  %s" % (args.form_id, rows[0].get("业务对象") or ""))

    entities = collections.OrderedDict()
    for row in rows:
        key = row.get("实体") or "FBillHead"
        entities[key] = entities.get(key, 0) + 1
    print("entities: %s" % ", ".join("%s(%d)" % kv for kv in entities.items()))

    exists = collections.Counter(row.get("存在") or "?" for row in rows)
    print("fields: %d   %s" % (
        len(rows),
        "  ".join("%s=%d" % kv for kv in exists.items()),
    ))
    print("source: fields_master.csv  (account metadata takes precedence)")

    needle = (args.find or "").strip()
    total = 0
    for entity in entities:
        selected = [r for r in rows if (r.get("实体") or "FBillHead") == entity]
        if needle:
            selected = [
                r for r in selected
                if needle in (r.get("字段key") or "") or needle in (r.get("中文字段名") or "")
            ]
        elif not args.all:
            selected = [r for r in selected if r.get("必录") == "Y"]
        if not selected:
            continue
        print("\n[%s]  %d field(s)" % (entity, len(selected)))
        print("  %-24s %-16s %-4s %-22s %-16s %s" % (
            "fieldKey", "字段名", "必录", "引用对象", "存在", "枚举 / Odoo 类型"))
        for row in selected:
            total += 1
            detail = row.get("枚举") or row.get("Odoo类型") or ""
            print("  %-24s %-16s %-4s %-22s %-16s %s" % (
                row.get("字段key") or "",
                (row.get("中文字段名") or "")[:14],
                row.get("必录") or "",
                row.get("引用对象") or "",
                row.get("存在") or "",
                detail[:52],
            ))

    if not total:
        print("\nno matching field")
        return 0

    if args.skeleton or not needle:
        print("\npayload skeleton (mandatory fields, header flat, entities nested):")
        print(json.dumps(skeleton_from_master(rows), ensure_ascii=False, indent=2)[:4000])
    return 0


# ----------------------------------------------------------------------
# Platform tree (legacy fallback)
# ----------------------------------------------------------------------
def load_metadata(kb, form_id):
    path = os.path.join(kb, "metadata", "%s.json" % form_id)
    if not os.path.isfile(path):
        raise SystemExit(
            "neither %s nor %s was found in the knowledge base:\n  %s\n"
            "Fetch the harvest first (see the SOP) or point --kb at it."
            % (MASTER_FILE, os.path.join("metadata", "%s.json" % form_id), kb))
    return json.load(io.open(path, encoding="utf-8"))


def entity_fields(entity):
    return entity.get("metaField") or []


def is_mandatory(field):
    return bool(field.get("mustInput") or field.get("isMustInput"))


def placeholder_legacy(field):
    if field.get("lookUpObjectID"):
        return {"FNumber": "..."}
    if field.get("fieldType") in (8,):
        return "False"
    if field.get("fieldType") in (21, 22, 2, 20):
        return 0
    if field.get("fieldType") in (4, 26, 28):
        return "2026-01-01"
    return "..."


def skeleton_legacy(entities):
    payload = {}
    for entity in entities:
        key = entity.get("entityKey")
        for field in entity_fields(entity):
            name = field.get("key") or field.get("fieldName")
            if not name:
                continue
            if key in HEADER_ENTITIES or not key:
                payload.setdefault(name, placeholder_legacy(field))
            else:
                payload.setdefault(key, {})[name] = placeholder_legacy(field)
    return payload


def render_legacy(args):
    print("WARNING: %s not found, falling back to the platform registration tree\n"
          "         (metadata/%s.json). Its mustInput flags are NOT the account's:\n"
          "         verify the mandatory fields with a real Save before trusting them.\n"
          % (MASTER_FILE, args.form_id))

    data = load_metadata(args.kb, args.form_id)
    entities = data.get("apiMetaEntity") or []
    print("%s  %s" % (args.form_id, data.get("name") or ""))
    print("entities: %s" % ", ".join(
        "%s(%d)" % (e.get("entityKey"), len(entity_fields(e))) for e in entities))

    needle = (args.find or "").strip()
    total = 0
    for entity in entities:
        rows = []
        for field in entity_fields(entity):
            if not args.all and not is_mandatory(field) and not needle:
                continue
            if needle and needle not in (field.get("key") or "") and needle not in (field.get("name") or ""):
                continue
            rows.append(field)
        if not rows:
            continue
        print("\n[%s]  %d field(s)" % (entity.get("entityKey"), len(rows)))
        print("  %-26s %-14s %-6s %-24s %s" % ("fieldKey", "字段名", "必录", "引用对象", "类型"))
        for field in rows:
            total += 1
            print("  %-26s %-14s %-6s %-24s %s" % (
                field.get("key") or field.get("fieldName"),
                (field.get("name") or "")[:12],
                "Y" if is_mandatory(field) else "",
                field.get("lookUpObjectID") or "",
                TYPE_HINT.get(field.get("fieldType"), "type=%s" % field.get("fieldType")),
            ))
    if not total:
        print("\nno matching field")
        return 0
    if args.skeleton or not needle:
        print("\npayload skeleton (header flat, entities nested):")
        print(json.dumps(skeleton_legacy(entities), ensure_ascii=False, indent=2)[:4000])
    return 0


# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("form_id", help="Kingdee business object, e.g. BD_Customer")
    parser.add_argument("--kb", default=DEFAULT_KB, help="path of the offline knowledge base")
    parser.add_argument("--find", help="only print fields whose key or name contains this")
    parser.add_argument("--all", action="store_true", help="list every field, not only the mandatory ones")
    parser.add_argument("--skeleton", action="store_true", help="print the mandatory field skeleton")
    parser.add_argument("--legacy", action="store_true",
                        help="read the platform registration tree instead of the master index")
    args = parser.parse_args()

    if not args.legacy:
        rows = load_master(args.kb, args.form_id)
        if rows is not None:
            return render_master(rows, args)
    return render_legacy(args)


if __name__ == "__main__":
    sys.exit(main())
