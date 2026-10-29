# Overlay module carrying this project's Chinese (zh_CN) translations for Odoo 19.
#
# The translations themselves live in i18n/<lang>.po next to this file; this
# module only exists so that they survive a synchronisation of the upstream
# addons/ tree.  Every other file reads its own directory name, so renaming the
# directory renames the module.  Keep `post_load` and set `version` to
# <odoo_version>.x.y.z.
{
    'name': 'SN WSD Chinese Translations',
    'summary': 'Supplies and overrides the Chinese (zh_CN) translations of other modules without touching upstream sources',
    'description': """
SN WSD Chinese translation overlay (Odoo 19)
============================================

Single place where this project keeps the Chinese translations it has to add
to, or override in, modules it does not own.  They are never written into the
upstream `addons/` tree, which a synchronisation with upstream (a fresh clone,
`git reset --hard`) would erase.

Data terms (records, field labels, views, mail templates, ...) are read from
this module's `i18n/zh_CN.po` by Odoo itself, when the module is installed or
upgraded.  Their entries point at the xmlid of the record they translate, so
any module can be covered.  Odoo runs that import while it is still walking the
module graph, when the models of the modules loaded after this one do not exist
yet, and silently drops those entries; `models/ir_module_module.py` therefore
imports the file a second time once the registry is complete.

Code terms (python `_()`, JS `_t()`, QWeb) are only ever read from the po file
of the module that *declares* the string, so no po file can translate another
module's terms.  This module merges its own entries into
`odoo.tools.translate.code_translations`, the runtime cache those lookups go
through, while it loads; see `code_translation_overlay.py`.

The editable archive of the translations is `myaddons/translations/zh_CN/`, and
the `i18n/zh_CN.po` file of this module is generated from it with the
`odoo-zh-i18n` skill:

    i18n_apply.py build myaddons/translations/zh_CN \
        --module-dir myaddons/sn_odoo19_translations --write

The generated file must not be edited by hand.  After an upstream pull the
translations are still in place: only the terms upstream added need work.
""",
    'version': '19.0.1.1.0',
    'author': 'SNCIC',
    'license': 'LGPL-3',
    'category': 'Hidden',
    'depends': ['base'],
    'post_load': 'post_load',
    'installable': True,
    'application': False,
}
