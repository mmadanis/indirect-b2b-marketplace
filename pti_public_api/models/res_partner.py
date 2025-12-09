from odoo import api, fields, models, _
from datetime import date, datetime
import uuid

class Partner(models.Model):
    _inherit = "res.partner"