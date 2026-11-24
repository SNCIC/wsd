"""Word output of the purchase contracts.

The document repeats the printed A4 contract of
``purchase_contract_default_templates.xml`` (default flavour) and of
``purchase_contract_templates.xml`` (Xinpeng flavour) with the real page
geometry (A4, 8 mm margins, SimSun 10.5 pt), so that the purchasing team can
retype a value, print the file and sign it. Every label is an English message
translated with the language of the user, like the labels of the other documents
of the module.
"""

import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from .purchase_contract_document import (
    FLAVOUR_DEFAULT,
    PARTY_ROWS,
    contract_blocks,
    contract_document_values,
)

FONT_NAME = 'SimSun'
BODY_SIZE = 10.5
TITLE_SIZE = 20
TITLE_LETTER_SPACING_PT = 8
FOOTER_SIZE = 9
MARGIN_MM = 8
CONTENT_WIDTH_MM = 210 - 2 * MARGIN_MM
LOGO_HEIGHT_MM = 12
TWIPS_PER_MM = 1440 / 25.4

# Columns of the header, of the parties block and of the products table, in
# millimetres, following the proportions of the QWeb templates.
HEADER_COLUMNS = (60.0, 74.0, 60.0)
PARTY_COLUMNS = (58.2, 48.5, 87.3)
PRODUCT_COLUMNS = (
    (9.7, 'No.', 'index', 'center'),
    (36.9, 'Material Code', 'code', 'left'),
    (31.0, 'Product Name', 'name', 'left'),
    (31.0, 'Specification', 'specification', 'left'),
    (13.6, 'Brand', 'brand', 'left'),
    (9.7, 'Unit', 'unit', 'center'),
    (19.4, 'Quantity', 'quantity', 'right'),
    (21.3, 'Tax Included Unit Price', 'price', 'right'),
    (21.4, 'Tax Included Amount', 'amount', 'right'),
)

# Run properties that follow the letter spacing in the schema: it has to be
# inserted before them, otherwise Word ignores the whole run properties block.
SPACING_SUCCESSORS = (
    'w:w', 'w:kern', 'w:position', 'w:sz', 'w:szCs', 'w:highlight', 'w:u',
    'w:effect', 'w:bdr', 'w:shd', 'w:fitText', 'w:vertAlign', 'w:rtl', 'w:cs',
    'w:em', 'w:lang', 'w:eastAsianLayout', 'w:specVanish', 'w:oMath',
)

ALIGNMENTS = {
    'left': WD_ALIGN_PARAGRAPH.LEFT,
    'center': WD_ALIGN_PARAGRAPH.CENTER,
    'right': WD_ALIGN_PARAGRAPH.RIGHT,
}


def build_purchase_contract_docx(orders, flavour=FLAVOUR_DEFAULT):
    """Return the .docx bytes of the purchase contract of `orders`."""
    translate = orders.env._
    values_list = [contract_document_values(order, translate, flavour)
                   for order in orders]
    return build_document(values_list, translate, flavour)


def build_document(values_list, translate, flavour=FLAVOUR_DEFAULT):
    """Return the .docx bytes of the contracts of `values_list`.

    One contract per order, each one starting on a new page.
    """
    document = Document()
    _setup_page(document)
    _add_footer(document.sections[0], translate)
    for index, values in enumerate(values_list):
        if index:
            document.add_page_break()
        _add_contract(document, values, translate, flavour)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _add_contract(document, values, translate, flavour):
    _add_heading(document, values, translate)
    # Word joins two tables that follow each other without a paragraph between
    # them: the narrow spacer keeps the header and the parties block apart.
    _spacer(document)
    _add_parties(document, values, translate, flavour)
    for kind, content in contract_blocks(translate, flavour):
        if kind == 'para':
            _write(_paragraph(document, line_spacing=1.3), content)
        elif kind == 'para_bold':
            _write(_paragraph(document), content, bold=True)
        elif kind == 'para_broken':
            paragraph = _paragraph(document, line_spacing=1.3)
            for index, text in enumerate(content):
                if index:
                    paragraph.add_run().add_break()
                _write(paragraph, text)
        elif kind == 'title':
            _write(_paragraph(document, space_before=4, keep_with_next=True),
                   content, bold=True)
        elif kind == 'section':
            _write(_paragraph(document, space_before=4), content, bold=True)
        elif kind == 'products':
            _add_product_table(document, values, translate)
        elif kind == 'delivery':
            _add_delivery_date(document, content)
        elif kind == 'signatures':
            _add_signatures(document, values, translate, flavour)


def _add_heading(document, values, translate):
    """Company mark on the left, contract title in the middle."""
    table = document.add_table(rows=1, cols=len(HEADER_COLUMNS))
    _set_table_grid(table, HEADER_COLUMNS)
    logo_cell, title_cell, _unused = table.rows[0].cells
    logo_cell.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM
    mark_paragraph = _cell_paragraph(logo_cell)
    if values['logo']:
        try:
            mark_paragraph.add_run().add_picture(
                io.BytesIO(values['logo']), height=Mm(LOGO_HEIGHT_MM))
        except Exception:  # noqa: BLE001 - python-docx only reads raster images
            # A PDF or a vector logo cannot be embedded: fall back on the name.
            _write(mark_paragraph, values['company_name'], bold=True, size=15)
    else:
        _write(mark_paragraph, values['company_name'], bold=True, size=15)

    title_paragraph = _cell_paragraph(title_cell, align='center')
    title_run = _write(title_paragraph,
                       translate('Purchase and Sales Contract'),
                       bold=True, size=TITLE_SIZE)
    title_run._element.get_or_add_rPr().insert_element_before(
        _run_spacing(TITLE_LETTER_SPACING_PT), *SPACING_SUCCESSORS)


def _add_parties(document, values, translate, flavour):
    """Dates, contract number, both companies and their contact details."""
    rows = PARTY_ROWS[flavour]
    table = document.add_table(rows=len(rows), cols=len(PARTY_COLUMNS))
    _set_table_grid(table, PARTY_COLUMNS)
    for row, columns in zip(table.rows, rows):
        for cell, column in zip(row.cells, columns):
            if column is None:
                continue
            label, key, bold_value = column
            _set_cell(cell, translate(label), values[key], bold_label=True,
                      bold_value=bold_value)


def _add_product_table(document, values, translate):
    """Products of the order and the totals rows below them."""
    table = document.add_table(rows=1, cols=len(PRODUCT_COLUMNS))
    table.style = 'Table Grid'
    _set_table_grid(table, [width for width, _label, _key, _align
                            in PRODUCT_COLUMNS])
    _set_cell_margins(table)

    for cell, (_width, label, _key, _align) in zip(table.rows[0].cells,
                                                   PRODUCT_COLUMNS):
        _set_cell(cell, translate(label), bold_label=True, align='center')

    for line in values['lines']:
        cells = table.add_row().cells
        for cell, (_width, _label, key, align) in zip(cells, PRODUCT_COLUMNS):
            _set_cell(cell, line[key], align=align)

    for label, text, amount, leading in values['totals']:
        cells = table.add_row().cells
        # The label spans the leading columns, the amount in words the columns
        # up to the amount one, like the footer of the QWeb templates.
        label_cell = cells[0].merge(cells[leading - 1])
        text_cell = cells[leading].merge(cells[len(PRODUCT_COLUMNS) - 2])
        _set_cell(label_cell, label, bold_label=True)
        _set_cell(text_cell, text)
        _set_cell(cells[len(PRODUCT_COLUMNS) - 1], amount, align='right')


def _add_delivery_date(document, delivery):
    """Delivery sentence with the three blank fields of the paper form."""
    promise, labels, deadline = delivery
    paragraph = _paragraph(document, line_spacing=1.3)
    _write(paragraph, promise)
    for label in labels:
        _write(paragraph, ' ' * 6, underline=True)
        _write(paragraph, label)
    _write(paragraph, deadline)


def _add_signatures(document, values, translate, flavour):
    """Signature columns of the Buyer and of the Supplier."""
    table = document.add_table(rows=1, cols=2)
    _set_table_grid(table, (CONTENT_WIDTH_MM / 2, CONTENT_WIDTH_MM / 2))
    for cell, label, name in (
            (table.rows[0].cells[0], translate('Purchaser:'), values['buyer_name']),
            (table.rows[0].cells[1], translate('Supplier:'),
             values['supplier_name'])):
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        paragraph = _cell_paragraph(cell, space_before=6)
        _write(paragraph, label, bold=True)
        _write(paragraph, name)
        _write(paragraph, translate('(Seal)'))
        if flavour == FLAVOUR_DEFAULT:
            _write(_add_cell_paragraph(cell),
                   translate('Authorized Representative:'))
        _add_cell_paragraph(cell)
        _write(_add_cell_paragraph(cell), translate('Date:'))


def _setup_page(document):
    """A4 portrait with the 8 mm margins of the paperformat of the report."""
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(MARGIN_MM)
    section.right_margin = Mm(MARGIN_MM)
    section.top_margin = Mm(MARGIN_MM)
    section.bottom_margin = Mm(MARGIN_MM)
    section.footer_distance = Mm(4)

    style = document.styles['Normal']
    style.font.name = FONT_NAME
    style.font.size = Pt(BODY_SIZE)
    _force_east_asia(style.element.get_or_add_rPr())
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(1)
    style.paragraph_format.line_spacing = 1.15


def _add_footer(section, translate):
    """Centred page number, with the two Word page fields."""
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    label = translate('Page %s of %s')
    parts = label.split('%s')
    if len(parts) != 3:
        # Translators may drop a placeholder: keep the plain text then.
        _write(paragraph, label, size=FOOTER_SIZE)
        return
    _write(paragraph, parts[0], size=FOOTER_SIZE)
    _add_field(paragraph, 'PAGE')
    _write(paragraph, parts[1], size=FOOTER_SIZE)
    _add_field(paragraph, 'NUMPAGES')
    _write(paragraph, parts[2], size=FOOTER_SIZE)


def _add_field(paragraph, instruction):
    """Append a Word field (page number) to `paragraph`."""
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), instruction)
    run = OxmlElement('w:r')
    run_properties = OxmlElement('w:rPr')
    run_properties.append(_fonts_element())
    size = OxmlElement('w:sz')
    size.set(qn('w:val'), str(int(FOOTER_SIZE * 2)))
    run_properties.append(size)
    run.append(run_properties)
    text = OxmlElement('w:t')
    text.text = '1'
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def _paragraph(container, align=None, space_before=0, space_after=1,
               line_spacing=1.15, keep_with_next=False):
    paragraph = container.add_paragraph()
    return _configure_paragraph(paragraph, align, space_before, space_after,
                                line_spacing, keep_with_next)


def _spacer(document):
    """Nearly empty paragraph of 4 points, used between two tables."""
    paragraph = _paragraph(document, space_after=0)
    paragraph.paragraph_format.line_spacing = Pt(4)
    return paragraph


def _configure_paragraph(paragraph, align=None, space_before=0, space_after=1,
                         line_spacing=1.15, keep_with_next=False):
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(space_before)
    fmt.space_after = Pt(space_after)
    fmt.line_spacing = line_spacing
    fmt.keep_with_next = keep_with_next
    if align is not None:
        paragraph.alignment = ALIGNMENTS[align]
    return paragraph


def _write(paragraph, text, bold=False, size=BODY_SIZE, underline=False):
    run = paragraph.add_run('' if text is None else str(text))
    run.font.name = FONT_NAME
    run.font.size = Pt(size)
    run.font.bold = bold
    run.underline = underline
    _force_east_asia(run._element.get_or_add_rPr())
    return run


def _cell_paragraph(cell, align=None, space_before=0, space_after=1,
                    line_spacing=1.1):
    """Write in the first paragraph of `cell`, dropping a previous content."""
    paragraph = cell.paragraphs[0]
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    return _configure_paragraph(paragraph, align, space_before, space_after,
                                line_spacing)


def _add_cell_paragraph(cell, space_before=0, space_after=1, line_spacing=1.1):
    """Append a paragraph to `cell`, keeping the ones already written."""
    return _configure_paragraph(cell.add_paragraph(), None, space_before,
                                space_after, line_spacing)


def _set_cell(cell, *parts, **kwargs):
    """Fill `cell` with the (text, is_bold) `parts` and align them.

    Merged cells keep the paragraphs of the cells they swallow: they are
    dropped so the text of the merge stays on a single line.
    """
    align = kwargs.pop('align', 'left')
    bold_label = kwargs.pop('bold_label', False)
    bold_value = kwargs.pop('bold_value', False)
    vertical_alignment = kwargs.pop('vertical_alignment',
                                    WD_ALIGN_VERTICAL.CENTER)
    if kwargs:
        raise TypeError('Unexpected arguments: %s' % ', '.join(kwargs))
    for paragraph in cell.paragraphs[1:]:
        paragraph._element.getparent().remove(paragraph._element)
    paragraph = _cell_paragraph(cell, align=align)
    for index, text in enumerate(parts):
        if index % 2:
            bold = bold_value
        else:
            bold = bold_label
        if text:
            _write(paragraph, text, bold=bold)
    cell.vertical_alignment = vertical_alignment
    return paragraph


def _set_table_grid(table, widths_mm):
    """Fix the width of the columns so Word keeps the printed proportions."""
    # ``autofit`` already writes the fixed ``w:tblLayout`` of the table.
    table.autofit = False
    grid = table._tbl.find(qn('w:tblGrid'))
    if grid is not None:
        for column, width in zip(grid.findall(qn('w:gridCol')), widths_mm):
            column.set(qn('w:w'), str(int(round(width * TWIPS_PER_MM))))
    for row in table.rows:
        for cell, width in zip(row.cells, widths_mm):
            cell.width = Mm(width)


def _set_cell_margins(table, twips=28):
    """Tighten the padding of the cells of the products table."""
    margins = OxmlElement('w:tblCellMar')
    for side in ('top', 'left', 'bottom', 'right'):
        margin = OxmlElement('w:%s' % side)
        margin.set(qn('w:w'), str(twips))
        margin.set(qn('w:type'), 'dxa')
        margins.append(margin)
    table._tbl.tblPr.insert_element_before(
        margins, 'w:tblLook', 'w:tblCaption', 'w:tblDescription',
        'w:tblPrChange')


def _run_spacing(points):
    """Letter spacing of the title, in twentieths of a point."""
    spacing = OxmlElement('w:spacing')
    spacing.set(qn('w:val'), str(int(points * 20)))
    return spacing


def _fonts_element():
    fonts = OxmlElement('w:rFonts')
    fonts.set(qn('w:ascii'), FONT_NAME)
    fonts.set(qn('w:hAnsi'), FONT_NAME)
    fonts.set(qn('w:eastAsia'), FONT_NAME)
    return fonts


def _force_east_asia(run_properties):
    """Point the East Asian font on `run_properties` at the Chinese face.

    Without it Word falls back on the theme font for the Chinese characters and
    the document no longer looks like the printed contract.
    """
    fonts = run_properties.get_or_add_rFonts()
    fonts.set(qn('w:ascii'), FONT_NAME)
    fonts.set(qn('w:hAnsi'), FONT_NAME)
    fonts.set(qn('w:eastAsia'), FONT_NAME)
