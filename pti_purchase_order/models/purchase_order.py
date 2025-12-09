from odoo import fields, models, api, _
import json
from odoo.tools.float_utils import float_round

import logging

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'