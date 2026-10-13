#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print the mapping material of a Kingdee business object (offline, read-only).

Reads the metadata harvested from the Kingdee open platform and prints, for one
``formId``:

* the entity tree (header, entries, sub entries) with its field count,
* every field the metadata marks as mandatory, with its entity and, for base
  data references, the object it points to,
* a payload skeleton nested per entity, ready to adapt in ``_kingdee_payload()``.

Usage::

    python tools/probe_form.py BD_Customer
    python tools/probe_form.py BD_Customer --find 币别
    python tools/probe_form.py BD_MATERIAL --all

The knowledge base path defaults to the local harvest; override it with
``--kb`` or the ``KINGDEE_KB`` environment variable.
"""

import argparse
import io
import json
import os
import sys

DEFAULT_KB = os.environ.get("KINGDEE_KB", r"D:/odoo/odoo-kingdee/data/kingdee-openapi")

# fieldType is a Kingdee internal code; these are the ones identified from the
# statistical profile of the whole field index (see the feasibility study).
TYPE_HINT = {
    1: "Char", 13: "Many2one", 8: "Boolean", 9: "Selection", 21: "Float(金额)",
    4: "Date", 22: "Float(数量)", 2: "Float(率)", 40: "Selection",
    18: "Many2one(SEC_User)", 36: "Char", 7: "Many2one(组织)", 26: "Datetime",
    28: "Datetime", 6: "Text", 20: "Float(单价)", 3: "Integer",
}

HEADER_ENTITIES = ("FBillHead",)


def load_metadata(kb, form_id):
    path = os.path.join(kb, "metadata", "%s.json" % form_id)
    if not os.path.isfile(path):
        raise SystemExit(
            "metadata not found: %s\n"
            "Fetch it first (see the SOP) or point --kb at the knowledge base." % path)
    return json.load(io.open(path, encoding="utf-8"))


def entity_fields(entity):
    return entity.get("metaField") or []


def is_mandatory(field):
    return bool(field.get("mustInput") or field.get("isMustInput"))


def placeholder(field):
    if field.get("lookUpObjectID"):
        return {"FNumber": "..."}
    if field.get("fieldType") in (8,):
        return "False"
    if field.get("fieldType") in (21, 22, 2, 20):
        return 0
    if field.get("fieldType") in (4, 26, 28):
        return "2026-01-01"
    return "..."


def skeleton(entities):
    """Payload skeleton: header fields flat, entity fields nested."""
    payload = {}
    for entity in entities:
        key = entity.get("entityKey")
        for field in entity_fields(entity):
            name = field.get("key") or field.get("fieldName")
            if not name:
                continue
            if key in HEADER_ENTITIES or not key:
                payload.setdefault(name, placeholder(field))
            else:
                payload.setdefault(key, {})[name] = placeholder(field)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("form_id", help="Kingdee business object, e.g. BD_Customer")
    parser.add_argument("--kb", default=DEFAULT_KB, help="path of the offline knowledge base")
    parser.add_argument("--find", help="only print fields whose key or name contains this")
    parser.add_argument("--all", action="store_true", help="list every field, not only the mandatory ones")
    parser.add_argument("--skeleton", action="store_true", help="print the mandatory field skeleton")
    args = parser.parse_args()

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
        print(json.dumps(skeleton(entities), ensure_ascii=False, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
