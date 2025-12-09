# -*- coding: utf-8 -*-
from odoo import fields, models, api, _

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"