from odoo import http
from odoo.http import request


class SnLabelPreviewController(http.Controller):
    """Live preview PNG for label templates (design decision 5).

    ``/sn_wsd_label/preview/<template_id>[/<res_id>]`` renders the template
    against the given record (or the template's preview record) so the
    designer can refresh a plain <img> without touching a printer.
    """

    @http.route(['/sn_wsd_label/preview/<int:template_id>',
                 '/sn_wsd_label/preview/<int:template_id>/<int:res_id>'],
                type='http', auth='user', multilang=False)
    def preview(self, template_id, res_id=None, **kwargs):
        template = request.env['sn.label.template'].browse(template_id).exists()
        if not template:
            return request.not_found()
        if res_id:
            record = request.env[template.model_id.model].browse(res_id).exists()
            if not record:
                return request.not_found()
            renderer = request.env['sn.label.renderer']
            data = renderer._png_bytes(
                renderer.render_png_image(template._to_layout_dict(), record))
        else:
            data = template._preview_png_bytes()
        return request.make_response(data, [('Content-Type', 'image/png')])
