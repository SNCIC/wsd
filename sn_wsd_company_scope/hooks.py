import logging

_logger = logging.getLogger(__name__)

# Root name prefixes used by the two production companies. A root that matches
# none of them keeps its categories shared, which is the safe default: a shared
# category stays visible to every company instead of disappearing.
DOMESTIC_ROOT_PREFIX = 'Material'
SECOND_ROOT_PREFIX = '南锦'
SECOND_COMPANY_HINT = '南锦'


def post_init_hook(env):
    """Assign the existing category trees to their company.

    The hook runs once, when the module is installed, so the categories created
    before the module existed get a company. Categories outside a known root are
    left shared on purpose.
    """
    Company = env['res.company']
    Category = env['product.category']

    domestic_company = Company.search([], order='id', limit=1)
    second_company = Company.search([('name', 'ilike', SECOND_COMPANY_HINT)], limit=1)

    assigned = 0
    for root in Category.search([('parent_id', '=', False)]):
        name = (root.name or '').strip()
        if name.startswith(SECOND_ROOT_PREFIX):
            company = second_company
        elif name.startswith(DOMESTIC_ROOT_PREFIX):
            company = domestic_company
        else:
            _logger.info(
                'Company scope: the category root "%s" matches no known company, '
                'its tree stays shared.', name)
            continue
        if not company:
            _logger.warning(
                'Company scope: no company found for the category root "%s", '
                'its tree stays shared.', name)
            continue
        tree = Category.search([('id', 'child_of', root.id)])
        tree.write({'company_id': company.id})
        assigned += len(tree)
        _logger.info('Company scope: %s categories of "%s" assigned to %s.',
                     len(tree), name, company.name)

    _logger.info('Company scope: %s categories assigned to a company.', assigned)
