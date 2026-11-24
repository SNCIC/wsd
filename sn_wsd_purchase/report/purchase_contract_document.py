"""Content of the purchase contracts, shared by the editable Word export.

``contract_document_values()`` reads one order into the values the document is
built from, and ``contract_blocks()`` describes the clauses in reading order, so
the two contract flavours (the default one and the Xinpeng one) only differ by
their data and by their list of blocks.
"""

FLAVOUR_DEFAULT = 'default'
FLAVOUR_XINPENG = 'xinpeng'

DEFAULT_SIGNING_LOCATION = '浙江省温州乐清市'

# Labels of the six columns of a party row: (label, value key, bold value).
# The middle column of each row stays empty, as in the printed contract.
_COMMON_PARTY_ROWS = (
    (('Signing Date:', 'signing_date', False),
     ('Signing Location:', 'signing_location', False),
     ('Contract No.:', 'contract_number', False)),
    (('Purchaser:', 'buyer_name', True), None, ('Supplier:', 'supplier_name', True)),
)

PARTY_ROWS = {
    FLAVOUR_DEFAULT: _COMMON_PARTY_ROWS + (
        (('Bank:', 'buyer_bank', False), None, ('Bank:', 'supplier_bank', False)),
        (('Account No.:', 'buyer_account', False), None,
         ('Account No.:', 'supplier_account', False)),
    ),
    FLAVOUR_XINPENG: _COMMON_PARTY_ROWS + (
        (('Address:', 'buyer_address', False), None,
         ('Address:', 'supplier_address', False)),
        (('Phone:', 'buyer_phone', False), None, ('Phone:', 'supplier_phone', False)),
        (('Bank:', 'buyer_bank', False), None, ('Bank:', 'supplier_bank', False)),
        (('Account No.:', 'buyer_account', False), None,
         ('Account No.:', 'supplier_account', False)),
    ),
}

# Technical requirements paragraph of each flavour.
TECHNICAL_REQUIREMENTS = {
    FLAVOUR_DEFAULT:
        "The quality standard of the products shall, in principle, comply with "
        "the national, the industrial and the local standards. Where the parties "
        "have special requirements on the quality or the technology of the "
        "products, those requirements shall be defined in an annex; where there "
        "is no special requirement, the standards above apply. Where the parties "
        "need to confirm samples, the samples may be sealed jointly by both "
        "parties and kept sealed by both parties and by a third party.",
    FLAVOUR_XINPENG:
        "The products shall be accepted according to the technical agreement and "
        "the drawings signed by the two parties; where there is no special "
        "agreement, the national and the industrial standards apply.",
}


def contract_document_values(order, translate, flavour=FLAVOUR_DEFAULT):
    """Return the values the contract of `order` is built from."""
    order.ensure_one()
    company = order.company_id
    buyer = company.partner_id
    supplier = order.partner_id
    buyer_bank = _first_bank(buyer, order.company_id)
    supplier_bank = _first_bank(supplier.commercial_partner_id, order.company_id)
    signing_date = order.signing_date or order.date_order
    lines = []
    for index, line in enumerate(order.order_line.filtered(
            lambda item: not item.display_type and item.product_qty != 0), start=1):
        lines.append({
            'index': index,
            'code': line.product_id.default_code or '',
            'name': line.product_id.name or line.name,
            'specification': line.product_id.material_specification or '',
            'brand': line.product_id.brand_id.name or '',
            'unit': line.product_uom_id.name or '',
            'quantity': order._format_contract_quantity(line.product_qty),
            'price': order._format_contract_unit_price(line.price_unit_tax_included),
            'amount': order._format_contract_amount(line.price_total),
        })
    return {
        'order_name': order.name,
        'contract_number': order.contract_number or order.name,
        'signing_date': order._format_contract_date(signing_date),
        'signing_location': order.signing_location or DEFAULT_SIGNING_LOCATION,
        'company_name': company.display_name,
        'logo': company.logo,
        'buyer_name': buyer.name,
        'supplier_name': supplier.name,
        'buyer_address': order._get_contract_address(buyer),
        'supplier_address': order._get_contract_address(supplier),
        'buyer_phone': buyer.phone or '',
        'supplier_phone': supplier.phone or '',
        'buyer_bank': buyer_bank.bank_id.name if buyer_bank.bank_id else '',
        'supplier_bank': supplier_bank.bank_id.name if supplier_bank.bank_id else '',
        'buyer_account': buyer_bank.acc_number or '',
        'supplier_account': supplier_bank.acc_number or '',
        'lines': lines,
        'totals': _contract_totals(order, translate, flavour),
    }


def _first_bank(partner, company):
    """Return the bank account of `partner` usable by `company`, if any."""
    return partner.bank_ids.filtered_domain(
        ['|', ('company_id', '=', False), ('company_id', '=', company.id)])[:1]


def _contract_totals(order, translate, flavour):
    """Rows below the products: (label, amount in words, amount, merged cells)."""
    if flavour == FLAVOUR_XINPENG:
        # The Xinpeng contract has no VAT row and prints plain amounts.
        return [
            (translate('Total Amount (incl. 13% VAT)'), order.amount_total_chinese,
             order._format_contract_total(order.amount_total), 2),
            (translate('Untaxed Amount'), order.amount_untaxed_chinese,
             order._format_contract_total(order.amount_untaxed), 2),
        ]
    return [
        (translate('Total Amount (incl. 13% VAT)'), order.amount_total_chinese,
         order._format_contract_total(order.amount_total), 3),
        (translate('Untaxed Amount'), order.amount_untaxed_chinese,
         order._format_contract_yuan(order.amount_untaxed), 3),
        (translate('VAT Amount'), order.amount_tax_chinese,
         order._format_contract_yuan(order.amount_tax), 3),
    ]


def contract_blocks(translate, flavour=FLAVOUR_DEFAULT):
    """Return the blocks of the contract body, in reading order.

    Each block is a ``(kind, content)`` pair: ``para`` and ``para_bold`` are one
    paragraph, ``para_broken`` a paragraph split on several lines, ``title`` a
    clause heading, ``section`` a bold clause holding its own text, ``products``
    the products table, ``delivery`` the delivery date line with its blanks and
    ``signatures`` the signature block.
    """
    if flavour == FLAVOUR_XINPENG:
        return _xinpeng_blocks(translate)
    return _default_blocks(translate)


def _opening_blocks(translate, flavour):
    """Intro, products, technical requirements and delivery date."""
    return [
        ('para', translate(
            "The Buyer and the Supplier, in accordance with the principles of "
            "equality and mutual benefit, equivalent exchange and unanimity "
            "through consultation, hereby agree on the purchase and supply of "
            "the products as follows:")),
        ('title', translate('1. List of the Purchased Products')),
        ('products', None),
        ('title', translate('2. Technical Requirements')),
        ('para', translate(TECHNICAL_REQUIREMENTS[flavour])),
        ('title', translate('3. Delivery Date:')),
        ('delivery', (
            translate('The Supplier undertakes to deliver the products on'),
            (translate('Year'), translate('Month'), translate('Day')),
            translate('(the date on which the products pass the incoming '
                      'inspection prevails).'),
        )),
        ('para_bold', translate('Other remarks:')),
    ]


def _default_blocks(translate):
    return _opening_blocks(translate, FLAVOUR_DEFAULT) + [
        ('title', translate('4. Delivery and Assumption of Risk')),
        ('para', translate(
            "The place of delivery is No. 181, Shiyi Road, Economic Development "
            "Zone, Yueqing City, Zhejiang Province, and the risk passes once the "
            "products reach the place designated by the Buyer and pass its "
            "inspection. The delivery note and the factory inspection report "
            "shall be provided on delivery, and any transport cost incurred in "
            "the process shall be borne by the Supplier.")),
        ('title', translate('5. Inspection')),
        ('para', translate(
            "The inspection period for the quantity and the appearance of the "
            "products shall be at least 3 working days, and the inspection "
            "period for the quality of the products shall be at least 15 working "
            "days. In addition, the quality guarantee period shall be at least 1 "
            "year from the date of acceptance. During the guarantee period, for "
            "any quality problem that is not attributable to the Buyer, the "
            "Supplier shall compensate the Buyer for its losses - where the loss "
            "is hard to determine, the compensation shall be at least 5,000 yuan "
            "- and shall be liable for the repair, the replacement and the "
            "return of the goods, all costs of which shall be borne by the "
            "Supplier. Where the Buyer raises the issue through the contact "
            "details or the agent stated in this contract, the Supplier shall "
            "reply within 2 days.")),
        ('title', translate('6. Settlement and Payment')),
        ('para_broken', (
            translate(
                "1. The parties shall settle and confirm the value of the goods "
                "of the week or of the delivery before the 10th day of the month "
                "following the month of the payment, or within 7 working days "
                "after each delivery;"),
            translate('2. Time of payment: according to the payment term agreed by '
                      'the parties;'),
            translate('3. Method of payment: bank transfer or acceptance bill;'),
            translate(
                "4. The Supplier issuing a lawful invoice in full and in advance "
                "is a precondition for the payment of the Buyer, and the Supplier "
                "shall issue its invoice before the 25th day of the month "
                "following the month in which the Buyer receives the goods."),
        )),
        ('title', translate('7. Liability for Breach of Contract')),
        ('para_broken', (
            translate(
                "1. In case of late delivery by the Supplier, including the case "
                "where the goods fail the inspection and are returned, replaced "
                "or repaired, the Supplier shall, in addition to compensating all "
                "the losses of the Buyer, such as a line stop or a failure to "
                "deliver to the customer of the Buyer in time, pay the Buyer "
                "liquidated damages for the delay, calculated at 0.05% per day on "
                "the value of the goods not yet delivered; where the delivery is "
                "more than 20 days late, the Buyer has the right to terminate the "
                "contract;"),
            translate(
                "2. The Supplier must guarantee that the products covered by this "
                "contract are genuine original products of the brand agreed by "
                "the parties. In case of counterfeit, shoddy or unqualified "
                "products, the Buyer has the right to terminate the contract "
                "unilaterally, to stop the payment and to recover all the payment "
                "already made; the Supplier shall compensate the Buyer for all the "
                "economic losses arising therefrom and shall pay the Buyer "
                "liquidated damages of no less than 25% of the total value of the "
                "goods;"),
            translate(
                "3. Where the Supplier has to take back the goods because of a "
                "failed inspection, a termination of the contract or any other "
                "reason, it shall take back the goods returned by the Buyer within "
                "three days after receiving the notice of the Buyer; otherwise it "
                "shall pay the Buyer a storage fee, which, where hard to "
                "determine, shall be calculated at 100 yuan per day, and where "
                "this is more than 15 days late, the Supplier shall be deemed to "
                "have waived the ownership of the goods and the Buyer has the "
                "right to dispose of them;"),
            translate(
                "4. Except as otherwise agreed in this contract, where the "
                "Supplier has an amount to refund but fails to do so, it shall "
                "refund within three days after receiving the notice of the "
                "Buyer; otherwise it shall pay the Buyer liquidated damages or "
                "occupation fees calculated at 0.05% per day on the amount to be "
                "refunded."),
        )),
        ('title', translate('8. Disputes Arising from the Performance')),
        ('para', translate(
            "Any dispute arising from the performance of this contract shall be "
            "settled by the parties through timely consultation; where the "
            "consultation fails, the dispute shall be filed with the people's "
            "court of the place where the Buyer is located. At the same time, the "
            "costs incurred by the observant party to protect its lawful rights "
            "shall be borne by the breaching party, including but not limited to "
            "the attorney fee, the litigation fee, the preservation fee, the "
            "guarantee fee, the travel expense, the lost working time and the meal "
            "expense. The basic information of the parties and the agents stated "
            "in this contract also serve as the valid contact information and "
            "contact persons of the parties for the performance of this contract, "
            "and any change shall be notified in writing within three days.")),
        ('title', translate('9. Effectiveness of this Contract')),
        ('para', translate(
            "This contract takes effect from the date of signing and is valid for "
            "two years. Upon expiry, the Buyer may decide whether to extend it for "
            "one more year. The faxes and the scanned copies of the contract "
            "confirmed by the Buyer in a certain way are valid, and a handwritten "
            "part shall not be altered a second time, otherwise it shall be "
            "deemed invalid.")),
        ('signatures', None),
    ]


def _xinpeng_blocks(translate):
    return _opening_blocks(translate, FLAVOUR_XINPENG) + [
        ('section', translate(
            "4. Place of Performance: the place of performance of this contract "
            "is Yueqing City, Zhejiang Province.")),
        ('section', translate(
            "5. Place of Delivery: \u25a1 the warehouse of the Buyer "
            "\u25a1 the forwarding office. The delivery note and the factory "
            "inspection report shall be provided on delivery.")),
        ('section', translate(
            "6. Inspection: the goods shall be inspected within 3 days after "
            "arrival; any doubt shall be raised to the Supplier within 10 days, "
            "and the Supplier shall reply within 2 days.")),
        ('section', translate(
            "7. Method of Payment: ____ monthly settlement / ____ telegraphic "
            "transfer / ____ acceptance bill (Buyer); the invoice of a monthly "
            "settlement shall be provided before the 25th day of the month "
            "following the arrival.")),
        ('title', translate('8. Liability for Breach of Contract:')),
        ('para_broken', (
            translate(
                "1. The Supplier must guarantee that the products covered by this "
                "contract are genuine products of the brand agreed by the parties. "
                "In case of counterfeit, shoddy or unqualified products, the Buyer "
                "has the right to terminate the contract unilaterally, to stop the "
                "payment and to recover the payment already made; the Supplier "
                "shall compensate the Buyer for all the economic losses arising "
                "therefrom;"),
            translate(
                "2. Where a quality problem or a defect of the products supplied "
                "by the Supplier, or a delay of the delivery, causes any economic "
                "loss to the Buyer, such as a line stop or a failure to deliver to "
                "the customer of the Buyer in time, the Supplier shall be liable "
                "for the compensation;"),
            translate(
                "3. Any dispute arising from the performance of this contract "
                "shall be settled by the parties through timely consultation; "
                "where the consultation fails, the dispute shall be filed with the "
                "people's court of the place where the Buyer is located."),
        )),
        ('section', translate(
            "9. Validity of the Contract: this contract takes effect from the date "
            "of signing and is valid for one year. The faxes and the scanned "
            "copies of the contract confirmed by the Buyer in a certain way are "
            "valid, and a handwritten part shall not be altered a second time, "
            "otherwise it shall be deemed invalid.")),
        ('signatures', None),
    ]
