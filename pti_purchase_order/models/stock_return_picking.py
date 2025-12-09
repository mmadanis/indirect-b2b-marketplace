from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round

class ReturnPickingLine(models.TransientModel):
    _inherit = "stock.return.picking.line"

    name = fields.Char('Description')

class ReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'
