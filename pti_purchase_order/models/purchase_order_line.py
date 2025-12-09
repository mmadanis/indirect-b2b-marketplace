# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.tools.float_utils import float_is_zero, float_compare
from odoo.exceptions import UserError
from datetime import datetime, date, timedelta
import logging

class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"
