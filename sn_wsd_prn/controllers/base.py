from odoo import http
from odoo.http import request
from werkzeug.exceptions import BadRequest

# The stream is ESC/P, not a document a browser can show: the RAW queue of the
# printer takes the bytes as they are.
PRN_CONTENT_TYPE = 'application/octet-stream'

# Records of one print job. A sheet is about 120 kB of graphics data, and the
# bridge hands the buffer to the spooler as a whole: the batch stays in a size
# a print queue takes without complaint.
MAX_RECORDS = 50


class SnPrnController(http.Controller):
    """Plumbing shared by the dot-matrix endpoints of the modules.

    Every sheet is handed out the same way: the identifiers of one record or of
    a selection are read from the query string, the records are browsed and
    their read right is checked, and the bytes of the sheets are returned as an
    attachment with its length, which the bridge needs to hand the buffer to
    the spooler in one piece.
    """

    def _sn_prn_records(self, model_name, ids):
        """Records of one identifier or of a comma separated selection."""
        try:
            record_ids = [int(value) for value in str(ids or '').split(',')
                          if value.strip()]
        except (TypeError, ValueError):
            raise request.not_found()
        if not record_ids:
            raise request.not_found()
        if len(record_ids) > MAX_RECORDS:
            raise BadRequest('Too many records in one print job: %s at most.'
                             % MAX_RECORDS)
        records = request.env[model_name].browse(record_ids).exists()
        if len(records) != len(record_ids):
            raise request.not_found()
        records.check_access('read')
        return records

    def _sn_prn_filename(self, prefix, records):
        """Name of the attachment: a selection names its first record."""
        if len(records) == 1:
            return '%s-%s.prn' % (prefix, _clean_name(records, 0))
        return '%s-%s-%s.prn' % (prefix, len(records), _clean_name(records, 0))

    def _sn_prn_response(self, data, filename):
        """Attachment the bridge sends unchanged to the printer queue."""
        return request.make_response(
            data,
            headers=[
                ('Content-Type', PRN_CONTENT_TYPE),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
                # The bridge hands the length of the buffer to the spooler: a
                # chunked response would be refused by a printer queue.
                ('Content-Length', str(len(data))),
                ('Cache-Control', 'no-store'),
            ])


def _clean_name(records, index):
    """Name of a record, without the slashes of a transfer reference."""
    record = records[index]
    return str(record.name or record.id).replace('/', '-')
