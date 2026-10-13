# -*- coding: utf-8 -*-
"""Sample real values of a Kingdee business object (read-only, no writes).

Run it inside Odoo so the credentials come from Settings::

    odoo-bin shell -c /etc/odoo19.conf -d odoo19 --no-http < tools/probe_live.py

It answers the two questions the offline knowledge base cannot: whether the field
keys of a mapping are accepted by the account, and which values a field really
holds in production.  For the **enum values of a Selection field prefer the
master index** (``fields_master.csv``, column ``枚举`` — e.g.
``python tools/probe_form.py BD_MATERIAL --find FErpClsID --all``): it is offline
and does not touch the account.  Come here only to confirm what the account
actually stores.  Adjust ``FORM_ID`` / ``FIELD_KEYS`` first.
"""

import collections

FORM_ID = "BD_Customer"
FIELD_KEYS = "FNumber,FName,FTRADINGCURRID.FNumber,FBillStatus,FCreateOrgId.FNumber"
FILTER = ""
SAMPLE = 5

client = env["sn.wsd.kingdee.client"]
rows = list(client.iter_bill_query(FORM_ID, FIELD_KEYS, filter_string=FILTER, page_size=SAMPLE))

print("PROBE form=%s rows=%d" % (FORM_ID, len(rows)))
for row in rows[:SAMPLE]:
    print("  %s" % row)

# Enum discovery: the metadata only knows that a field is a Selection, the
# options have to be read from real data (or confirmed by the business).
seen = collections.OrderedDict()
for row in rows:
    for key, value in row.items():
        seen.setdefault(key, set()).add(str(value))
print("distinct values per field:")
for key, values in seen.items():
    print("  %-28s %s" % (key, sorted(values)[:8]))

if not rows:
    print("WARNING: no row returned, check the field keys (MsgCode 9 = unknown field)")
