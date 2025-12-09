from email.policy import default
import opcode
from odoo import api, models, fields, _
from odoo.exceptions import UserError 
from datetime import datetime
from uuid import uuid4
import pandas as pd
import base64
import xlwt
import io
from io import BytesIO

import logging
import json
import math
import requests

class PurchaseOrderWizard(models.TransientModel):
    _name = "purchase.order.wizard"
    _description = "Purchase Order Wizard"

    upload_file = fields.Binary('Upload PO')
    filename = fields.Char('filename')

    def read_excel_po(self, excel_binary_data):
        data_frames = {}
        if not excel_binary_data:
            raise UserError(_('parameter excel_binary_data is required'))
        wb = pd.ExcelFile(io.BytesIO(base64.b64decode(excel_binary_data)))
        single_sheet_frame = wb.parse(wb.sheet_names[0])
        single_sheet_frame.columns = single_sheet_frame.columns.str.lower()
        if 'notes' not in single_sheet_frame.keys().str.lower():
            raise ValueError('[read_excel] column Notes is not found')

        frames = single_sheet_frame.groupby('notes').apply(lambda line: list(
            zip(line['vendor ref'], line['delivery date'], line['warehouse'], line['delivery to'], 
            line['product code'], line['product name'], line['qty'], line['row kompilasi'], line['requestor'], 
            line['top'], line['highlight'], line['incoterm'], line['taxes'])))

        note = frames.keys()

        for n in note:
            if not n or not isinstance(n, str):
                raise ValueError('[read_excel] invalid Notes format')
            upper_n = n.strip()
            if upper_n not in data_frames:
                data_frames[upper_n] = {}
                values = {}
                for vendor_ref, delivery_date, warehouse, delivery_to, product_code, product_name, qty, row_kompilasi, requestor, top, highlight, incoterm, taxes in frames[n]:
                    product_code = str(product_code).zfill(5)
                    if not product_code or '.' in product_code:
                        raise ValueError('[read_excel] invalid product_code')
                    if isinstance(qty, (float, int, str)) and qty > 0:
                        if isinstance(qty, str) and not qty.isdigit():
                            raise ValueError('[read_excel] invalid quantity format for this product: %s' % product_name)
                        if product_name not in values:
                            values[product_name] = [qty, vendor_ref, str(delivery_date), warehouse, delivery_to, product_code, row_kompilasi, requestor, top, highlight, incoterm, taxes]
                        elif product_name in values:
                            values[product_name][0] += qty
                    else:
                        raise ValueError('[read_excel] item %s has no quantity' % product_name)

                if values:
                    data_frames[upper_n] = sorted(values.items())
                else:
                    raise ValueError('[read_excel] note %s has no rows' % n)

        return data_frames

    def async_create_po(self, data_frames, recap_id):
        # ResPartner = self.env['res.partner'].sudo()
        if not data_frames:
            raise UserError(_('[async_create_po] there is no data to proceed'))
        if not recap_id:
            raise UserError(_('[async_create_po] parameter recap_id is required'))
        elif len(recap_id) != 1:
            raise UserError(_('[async_create_po] expected singleton of parameter recap_id'))
        celery = {
            'queue': 'create.oc', 'countdown': 2, 'retry': True,
            'retry_policy': {'max_retries': 2, 'interval_start': 2}
        }
        recap_line_values = []

        error_msg = {}
        for notes in data_frames:
            # error_msg[notes] = {}
            error_product = {}
        
            lines = data_frames[notes]
            ProductProduct = self.env['product.product'].sudo()
            ResPartner = self.env['res.partner'].sudo()
            StockPickingType = self.env['stock.picking.type'].sudo()
            PaymentTerm = self.env['account.payment.term'].sudo()
            StockIncoterms = self.env['stock.incoterms'].sudo()
            AccountTax = self.env['account.tax'].sudo()

            for product_name, values in lines:

                product_code = values[5]  
                error_check = []

                product_id = ProductProduct.search([('name', '=', product_name), ('default_code', '=', values[5])], limit=1)
                if not product_id:
                    error_check.append('product [%s] %s not found' % (values[5], product_name))

                vendor_id = ResPartner.search([('ref', '=', values[1])], limit=1)
                if not vendor_id:
                    error_check.append('vendor_ref %s not found' % values[1])

                delivery_date = values[2]
                try:
                    datetime.strptime(delivery_date[0:10], '%d-%m-%Y').date()
                except:
                    error_check.append('invalid format dd-mm-yyyy for this delivery_date %s' % values[2])

                picking_type_id = StockPickingType.search([('name', '=', values[4]), ('warehouse_id.name', '=', values[3])], limit=1)
                if not picking_type_id:
                    error_check.append('picking_type_id %s: %s not found' % (values[4], values[3]))
                
                requestor = ResPartner.search([('ref', 'ilike', values[7]),('is_employee','=',True)], limit=1)
                if not requestor:
                    error_check.append('requestor %s not found' % (values[7]))

                if (isinstance(values[8], float) and math.isnan(values[8])):
                    error_check.append('TOP cannot be empty')
                elif not (values[8] == 1 or values[8] == 2):
                    error_check.append('TOP is not in the correct format. The allowed format is 1/2')

                if not (isinstance(values[10], float) and math.isnan(values[10])):
                    incoterm_id = StockIncoterms.search([('name', '=', values[10])], limit=1)
                    if not incoterm_id:
                        error_check.append('incoterm_id %s not found' % (values[10]))

                if not (isinstance(values[11], float) and math.isnan(values[11])):
                    taxes = values[11].split('|')
                    for tax in taxes:
                        tax_id = AccountTax.search([('name', '=', tax)], limit=1)
                        if not tax_id:
                            error_check.append('tax_id %s not found' % (tax))
                
                if error_check:
                    error_product[product_code] = error_check

            if error_product:
                error_msg[notes] = error_product
        
        if error_msg:
            error_msg_display = ''
            for notes in error_msg:
                error_msg_display += "%s\n" %(str(notes))

                i = 0
                for product, error in error_msg[notes].items():
                    i += 1
                    error_msg_display += ("%s. %s => %s\n") % (str(i), str(product), str(error))
                error_msg_display += '\n'

            raise UserError(_(error_msg_display))
        
        else:
            for notes in data_frames:
                lines = data_frames[notes]
                self.env['celery.task'].call_task(
                    self._name,
                    '_task_create_po',
                    res_id=recap_id.id,
                    res_model=recap_id._name,
                    res_uid=self._uid,
                    notes=notes,
                    lines=lines,
                    previous_state='%s:%s' % ('state', recap_id.state),
                    celery=celery
                )
                recap_line_values.append((0, False, {'notes': notes}))

        recap_id.sudo().write({
            'user_id': self.env.user.id,
            'recap_lines': recap_line_values
        })

        return recap_id

    def _task_create_po(self, task_uuid, **kwargs):
        recap_id = self.env[kwargs.get('res_model')].sudo().browse(kwargs.get('res_id'))
        notes = kwargs.get('notes')
        lines = kwargs.get('lines')

        if notes and not lines:
            data_frames = self.read_excel_oc(recap_id.upload_file)
            if notes not in data_frames:
                raise ValueError('[_task_create_po] notes %s not found in excel data' % notes)
        elif not (notes or lines):
            raise ValueError('[_task_create_po] notes and lines are empty')
        po_id = self.create_po([(notes, lines)], recap_id, recreate=kwargs.get('recreate', False))
        if not po_id:
            raise ValueError('[_task_create_po] po_id is empty')

        return po_id.id
    
    def create_po(self, data, recap_id, recreate=False):
        if not data:
            raise ValueError('[create_po] parameter data is required. format: [(notes, items)]')

        ResPartner = self.env['res.partner'].sudo()
        ProductProduct = self.env['product.product'].sudo()
        StockPickingType = self.env['stock.picking.type'].sudo()
        PaymentTerm = self.env['account.payment.term'].sudo()
        StockIncoterms = self.env['stock.incoterms'].sudo()
        AccountTax = self.env['account.tax'].sudo()
        FiscalPosition = self.env['account.fiscal.position']
        dc = self.env['ir.config_parameter'].sudo().get_param('mass_upload_po.distribution_center')

        notes = data[0][0]
        lines = data[0][1]

        ref = [values[1] for product_name, values in lines]
        delivery_date = [values[2] for product_name, values in lines]
        warehouse = [values[3] for product_name, values in lines]
        delivery_to = [values[4] for product_name, values in lines]
        product_code = [values[5] for product_name, values in lines]
        row_kompilasi = [values[6] for product_name, values in lines]
        requestor = [values[7] for product_name, values in lines]
        top = [values[8] for product_name, values in lines]
        highlight = [values[9] for product_name, values in lines]
        incoterm = [values[10] for product_name, values in lines]
        # delivery_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        recap_line_id = self.env['purchase.order.recap.line'].sudo().search([
            ('recap_id', '=', recap_id.id),
            ('notes', '=', notes)
        ], limit=1)

        if not recap_line_id:
            raise ValueError('[create_po] recap_line_id cannot be found. notes: %s' % notes)
        if not recreate and recap_line_id.po_id:
            return recap_line_id.po_id

        vendor_id = ResPartner.search([('ref', '=', ref[0])], limit=1)
        picking_type_id = StockPickingType.search([('name', '=', delivery_to[0]), ('warehouse_id.name', '=', warehouse[0])], limit=1)
        date_planned = delivery_date[0]
        requestor = ResPartner.search([('ref', 'ilike', requestor[0]),('is_employee','=',True)], limit=1)
        
        if top[0] == 1:
            payment_term_id = vendor_id.property_supplier_payment_term_id
        elif top[0] == 2:
            payment_term_id = vendor_id.property_supplier_payment_term_id_2
        
        dc_id = ResPartner.search([('name', '=', dc), ('is_dc','=',True)], limit=1)
        incoterm_id = StockIncoterms.search([('name','=',incoterm[0])], limit=1) if not (isinstance(incoterm[0], float) and math.isnan(incoterm[0])) else False 
        
        fpos = FiscalPosition.get_fiscal_position(vendor_id.id)
        fpos = FiscalPosition.browse(fpos)
        
        po_values = {
            'partner_id': vendor_id.id,
            'currency_id': vendor_id.property_purchase_currency_id.id,
            'dc_id': dc_id.id,
            'date_planned': datetime.strptime(date_planned[0:10], '%d-%m-%Y').date(),
            'picking_type_id': picking_type_id.id,
            'origin': str(row_kompilasi[0]) + '/' + str(product_code[0]),
            'order_line': [],
            'request_id': requestor.id,
            'payment_term_id': payment_term_id.id if payment_term_id else False ,
            'incoterm_id': incoterm_id.id if incoterm_id else False,
            'is_po_direct': True,
            'fiscal_position_id': fpos.id
        }

        for product_name, values in lines:
            product_id = ProductProduct.search([('name', '=', product_name), ('default_code', '=', values[5])], limit=1)
            
            taxes_ids = []
            if not (isinstance(values[11], float) and math.isnan(values[11])):
                taxes = values[11].split('|')
                for tax in taxes:
                    tax_id = AccountTax.search([('name','=',tax)], limit=1)
                    taxes_ids.append(tax_id.id)

            if not product_id:
                raise ValueError('[create_po] product %s not found' % product_name)

            line_ids_val = {
                'product_id': product_id.id,
                'name': product_id.display_name,
                'date_planned': datetime.strptime(date_planned[0:10], '%d-%m-%Y').date(),
                'product_uom': product_id.uom_po_id.id or product_id.uom_id.id,
                'price_unit': 1,
                'product_qty': values[0],
                'taxes_id': [(6, 0, taxes_ids)] if taxes_ids else False
            }
            po_values['order_line'].append((0, False, line_ids_val))

        # create po
        po_id = self.env['purchase.order'].create(po_values)
        
        order_line = self.env['purchase.order.line'].search([('order_id','=',po_id.id)])
        notes_unit_price = ''
        for line in order_line:
            # store value from file
            input_product_qty = line.product_qty
            taxes_id = line.taxes_id
            data_planned_line = line.date_planned
            
            # reassign value from file after call method onchange
            line.onchange_product_id()
            line.product_qty = input_product_qty
            line.taxes_id = taxes_id
            line.date_planned = data_planned_line
            line.product_tmpl_id = line.product_id.product_tmpl_id

            # get base price
            base_price_unit, base_price_currency = line.get_incoterm_partner()
            if base_price_currency != 'IDR':
                notes_unit_price += 'Unit price base %s %s %s\n' % (line.name, base_price_currency, base_price_unit)

        po_id.get_exchange_rate() # fill exchange rate field
        po_id.sudo().onchange_exhange_rate() # update price unit depends on exchange rate
        
        # update date_planned
        po_id.date_planned = datetime.strptime(date_planned[0:10], '%d-%m-%Y').date()

        # assign tab advance payment
        res_payment_term = po_id.onchange_payment_term()
        po_id.write(res_payment_term['value'])

        # update notes
        if not (isinstance(highlight[0], float) and math.isnan(highlight[0])): 
            po_id.write({'notes': highlight[0] + '\n\n' + notes_unit_price + '\n' + po_id['notes']})
        else:
            po_id.write({'notes': notes_unit_price + '\n' + po_id['notes']})
            
        # update recap log
        recap_id.sudo().write({
            'recap_lines': [(1, recap_line_id.id, {
                'po_id': po_id.id
            })]
        })

        return po_id
    
    def upload_po(self):
        if not self.upload_file:
            raise UserError(_('please upload excel file'))
        # 1. read excel
        try:
            data_frames = self.read_excel_po(self.upload_file)
        except ValueError as e:
            raise UserError(e)

        # 2. create log/recap
        recap_id = self.env['purchase.order.recap'].sudo().create({
            'filename': self.filename,
            'upload_file': self.upload_file,
            'recap_lines': False
        })

        # 3. create po
        self.async_create_po(data_frames=data_frames, recap_id=recap_id)

    def download_template(self):
        book = xlwt.Workbook(encoding='UTF-8')
        style = xlwt.XFStyle()
        font = xlwt.Font()
        font.bold = True
        style.font = font
        data = {
            'Upload PO': ['Notes', 'Vendor Ref', 'Delivery Date', 'Warehouse', 'Delivery To', 'Product Code', 'Product Name', 'Qty', 'Row Kompilasi', 'Requestor', 'TOP', 'Highlight', 'Incoterm', 'Taxes']
        }
        for sheet_name in data:
            sheet = book.add_sheet(sheet_name)
            for idx, title in enumerate(data[sheet_name]):
                sheet.write(0, idx, title, style=style)
        data = BytesIO()
        book.save(data)
        attachment_values = {
            'name': '{} {} Mass Upload PO Template'.format(self._name, str(self.ids)),
            'datas_fname': 'Mass Upload PO Template.xlsx',
            'res_model': 'ir.ui.view',
            'res_id': False,
            'public': True,
            'datas': base64.encodebytes(data.getvalue()),
        }
        attachment_id = self.env['ir.attachment'].sudo().create(attachment_values)
        return {
            'name': 'Mass Upload PO Template',
            'type': 'ir.actions.act_url',
            'url': 'web/content/{}?download=true'.format(attachment_id.id),
            'target': 'new',
        }
    
    
    def trigger_po_indirect(self):
        url = self.env['ir.config_parameter'].sudo().get_param('po_indirect.webhook_po_indirect')
        # timeout = self.env['ir.config_parameter'].sudo().get_param('po_idirect.request_timeout', '60')
        basic_token = self.env['ir.config_parameter'].sudo().get_param('po_indirect.basic_token')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % basic_token
        }
        response = requests.post(url,headers=headers)
        logging.info("=====trigger_po_indirect=====")
        logging.info(response)
        
        if response.status_code != 200:
            raise UserError('''Error When Triggering Workflow:
                            Error: %s''' % response.text)
        
