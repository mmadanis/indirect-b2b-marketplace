from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
import logging

from uuid import uuid4
import pandas as pd
import base64

class PurchaseOrderRecap(models.Model):
    _name = "purchase.order.recap"
    _description = "Recap all result of uploaded PO"
    _rec_name = 'filename'

class PurchaseOrderRecapLine(models.Model):
    _name = "purchase.order.recap.line"