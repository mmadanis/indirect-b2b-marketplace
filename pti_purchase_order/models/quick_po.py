from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class SimplePurchaseOrder(models.Model):
    _name = 'simple.purchase.order'

class SimplePurchaseOrderLine(models.Model):
    _name = 'simple.purchase.order.line'
