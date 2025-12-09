# -*- coding: utf-8 -*-
import functools
from odoo import http, _
from odoo.exceptions import AccessError, AccessDenied
from base64 import b64decode
from werkzeug.urls import url_decode
import json
from odoo.http import request
from datetime import datetime, timedelta
import logging

user_system = 'it-support'

def basic_auth(func):
    @functools.wraps(func)
    def wrap(self, *args, **kwargs):
        # base64 encoded api_key & secret_key
        token = request.httprequest.headers.get('Authorization')
        if token:
            if not token.startswith('Basic'):
                raise AccessError('The Value of Authorization should be started with Basic')
            decoded = json.loads(b64decode(token.replace('Basic', '').strip()).decode('utf-8'))
            api_key = decoded.get('api_key')
            secret_key = decoded.get('secret_key')
            
            # validate secret key
            is_secret_key_valid = request.env['restapi.authentication'].validate_secret_key(api_key=api_key, secret_key=secret_key)
            if not is_secret_key_valid:
                raise AccessError('invalid secret_key')
            
            # validate uid
            search_user = """
            SELECT id FROM res_users WHERE api_key = %s AND secret_key = %s
            """
            cr = request.cr
            cr.execute(search_user, (api_key, secret_key))
            result = cr.dictfetchall()
            uid = False
            for line in result:
                if not line:
                    continue
                if line['id']:
                    uid = line['id']
            if not uid:
                raise AccessDenied('user not found')
            kwargs.update({'uid': uid})
            return func(self, *args, **kwargs)
        raise AccessError(_('Authorization is required'))
    return wrap


class PurchaseOrderApi(http.Controller):

    @basic_auth
    @http.route('/api/purchase/order/create', type='json', auth='public', methods=['POST'])
    def Create_PO(self, **kwargs):
        if request.httprequest.method == 'POST':
            try:
                raw_data = request.httprequest.data.decode('utf-8')
                input_data = json.loads(raw_data)
                is_po_direct = input_data['is_po_direct']
                incoterm_id = input_data['incoterm_id']
                currency_id = input_data['currency_id']
                payment_term_id = input_data['payment_term_id']
                date_order = datetime.strptime(input_data['date_order'], "%Y-%m-%d %H:%M:%S") - timedelta(hours=7) # subtract by 7 as odoo auto set it +7
                schedule_date = datetime.strptime(input_data['schedule_date'], "%Y-%m-%d %H:%M:%S") - timedelta(hours=7) # subtract by 7 as odoo auto set it +7
                fiscal_position_id = input_data['fiscal_position_id']
                partner_id = input_data['partner_id']
                tfm_doc = input_data['tfm_doc']
                order_lines = input_data['order_lines']
                requester_id = input_data['request_id']
                dc_id = input_data['dc_id']
                picking_type_id = input_data['picking_type_id']

                vendor = http.request.env['res.partner'].sudo().search([('id', '=', partner_id)], limit=1)
                if payment_term_id:
                    payment_term = http.request.env['account.payment.term'].sudo().search([('id', '=', payment_term_id)], limit=1)
                else:
                    payment_term = vendor.property_supplier_payment_term_id_2 or vendor.property_supplier_payment_term_id

                data_po = {
                    'date_order': date_order,
                    'dc_id': dc_id,
                    'partner_id': vendor.id,
                    'date_planned': schedule_date,
                    'picking_type_id': picking_type_id,
                    'vendor_code': vendor.ref,
                    'currency_id': currency_id,
                    'payment_term_id': payment_term_id,
                    'fiscal_position_id': fiscal_position_id,
                    'request_id': requester_id,
                    'tfm_doc': tfm_doc,
                    'incoterm_id': incoterm_id,
                    'is_po_direct': is_po_direct,
                    'is_advance': False,
                    'order_line': [],
                    'advance_payment_values': []
                }
                for order in order_lines:
                    product = http.request.env['product.product'].sudo().search([('id', '=', order['product_id'])], limit=1)
                    if not product:
                        raise ValueError(('product %s not found')% (order['name'],))
                    analytic_account = http.request.env['account.analytic.account'].sudo().search([('code', '=', order['account_analytic_id'])], limit=1)
                    
                    activity = None
                    if order['activity_id']:
                        activity = http.request.env['account.tfm.activity'].sudo().search([('id', '=', order['activity_id'])], limit=1)

                    if order['taxes_id']:
                        tax_id = http.request.env['account.tax'].sudo().search([('id', '=', order['taxes_id'])], limit=1)
                        if not tax_id:
                            raise ValueError(('tax with id %s not found')% (order['taxes_id'],))
                        fiscal_map = http.request.env['account.fiscal.position.tax'].sudo().search([('tax_src_id', '=', tax_id.id), ('position_id', '=', vendor.property_account_position_id.id)], limit=1)
                        if not fiscal_map:
                            raise ValueError(('vendor %s has fiscal position %s, but the tax has been post to odoo with id %s and the tax was not mapping in the fiscal position. PLEASE UPDATE FISCAL POSITION OF THE VENDOR')% (vendor.name, vendor.property_account_position_id.name, order['taxes_id']))
                    else:
                        raise ValueError(('vendor %s has fiscal position %s, but the tax has been post to odoo with id %s and the tax was not mapping in the fiscal position. PLEASE UPDATE FISCAL POSITION OF THE VENDOR')% (vendor.name, vendor.property_account_position_id.name, order['taxes_id']))

                    schedule_date_line = datetime.strptime(order['date_planned'], "%Y-%m-%d %H:%M:%S") - timedelta(hours=7)
                    data_po['order_line'].append((0, 0, {
                        'product_id': product.id,
                        'product_uom': product.uom_id.id,
                        'name': order['description'] if order['description'] else product.display_name,
                        'activity_id': activity.id if activity else False,
                        'account_analytic_id': analytic_account.id,
                        'product_qty': order['product_qty'],
                        'price_unit': order['price_unit'],
                        'date_planned': schedule_date_line,
                        'taxes_id': [(6, 0, [fiscal_map.tax_dest_id.id])] if fiscal_map.tax_dest_id else False
                    }))

                purchase_id = http.request.env['purchase.order'].sudo().create(data_po)
                if purchase_id:
                    if not payment_term and not payment_term.advance_payment:
                        purchase_id.is_advance = False

                    if payment_term.advance_payment:
                        query = 'select advance, value, days, value_amount from account_payment_term_line where advance = True and payment_id = %s'
                        http.request.env.cr.execute(query, (payment_term.id,))
                        data = http.request.env.cr.dictfetchall()
                        advance_percentage = 0
                        advance_payment_values = []
                        for line in data:
                            if not line:
                                continue
                            advance_percentage += int(line['value_amount'])
                            amount = float(float(line['value_amount'] / 100.0) * purchase_id.amount_total)
                            advance_payment_values.append((0, 0, {
                                'purchase_id': purchase_id.id,
                                'name': '{}% Advance'.format(str(round(line['value_amount'], 1))),
                                'invoice_id': False,
                                'percentage': line['value_amount'],
                                'amount': amount,
                                'days': line['days']
                            }))
                        if advance_percentage == 100:
                            purchase_id.is_advance = True
                        else:
                            purchase_id.is_advance = False
                        purchase_id.write({'advance_payment_ids': advance_payment_values})
                    
                    # confirm purchase order
                    purchase_id.apply_discount()
                    purchase_id.button_confirm()

                return {
                    'status': 'success',
                    'message': 'PO Successfully Created!',
                    'data': {
                        'input_data' : input_data,
                        'po_data' : {
                            'po_id': purchase_id.id,
                            'po_name': purchase_id.name,
                        },
                    },
                }

            except Exception as e:
                return {
                    'status': 'error',
                    'message': str(e),
                    'data': {
                        'input_data' : input_data
                    }
                }

    @basic_auth
    @http.route('/api/purchase/order/validation-transformation-error-list', type='json', auth='public', methods=['POST'])
    def ValidationPurchaseOrderErrorList(self, **kwargs):
        raw_data = request.httprequest.data.decode('utf-8')
        errors = [] 

        try:
            input_data = json.loads(raw_data)
            required_keys = {
                'partner_id': str,
                'dc': str,
                'requester': str,
                'tfm_doc': str,
                'payment_term': int,
                'order_date': int,
                'schedule_date': int,
                'incoterm': str,
                'picking_type': str,
                'order_lines': list,
                'partner_ref': str,
                'executed_at': str
            }

            # Validate Top-Level Keys
            for key, expected_type in required_keys.items():
                if key not in input_data:
                    errors.append("Missing required key: " + key)
                elif not isinstance(input_data[key], expected_type):
                    errors.append("Invalid data type for " + key + ". Expected " + expected_type.__name__ + ".")
                elif key != 'partner_ref' and input_data[key] in [None, '', [], {}, ' ']:
                    errors.append("The value for " + key + " cannot be empty.")

            # Validate partner_id
            partner = http.request.env['res.partner'].sudo().search([('ref', '=', input_data['partner_id'])], limit=1)
            if not partner:
                errors.append("partner_id " + str(input_data['partner_id']) + " does not exist in res.partner.")

            # Validate dc
            dc = http.request.env['res.partner'].sudo().search([('name', '=', input_data['dc'])], limit=1)
            if not dc:
                errors.append("dc (distribution center) " + input_data['dc'] + " does not exist in res.partner.")

            # Validate requester
            requester = http.request.env['res.partner'].sudo().search([('ref', '=', input_data['requester'])], limit=1)
            if not requester:
                errors.append("requester " + str(input_data['requester']) + " does not exist in res.partner.")

            # Validate tfm_doc
            if 'tfm_doc' in input_data and input_data['tfm_doc'] not in [None, '', [], {}, ' ']:
                valid_tfm_docs = ['TFM', 'NON-TFM', 'MARS']
                if input_data['tfm_doc'] not in valid_tfm_docs:
                    errors.append("tfm_doc " + input_data['tfm_doc'] + " is not valid. Valid options: TFM, NON-TFM, MARS.")

            # Check if incoterm exists
            incoterm = http.request.env['stock.incoterms'].sudo().search([('name', '=', input_data['incoterm'])], limit=1)
            if not incoterm:
                errors.append('incoterm "' + input_data['incoterm'] + '" does not exist in stock.incoterms.')

            # Check if picking_type exists
            picking_type = ''
            if 'picking_type' in input_data and input_data['picking_type'] != '':
                stock_picking = input_data['picking_type'].split(":")
                if len(stock_picking) == 2:
                    opt_type_name = stock_picking[1].strip()
                    warehouse = stock_picking[0].strip()

                    picking_type = http.request.env['stock.picking.type'].sudo().search([('name', '=', opt_type_name), ('warehouse_id.name', '=', warehouse)], limit=1)
                    if not picking_type:
                        errors.append('picking_type "' + input_data['picking_type'] + '" does not exist in stock.picking.type.')
                else: 
                    errors.append('invalid stock picking: ' + input_data['picking_type'])


            # check if fiscal position valid
            fpos = ''
            if input_data['partner_id'] not in [None, '', [], {}] :
                FiscalPosition = http.request.env['account.fiscal.position']
                fpos = FiscalPosition.get_fiscal_position(partner.id)
                fpos = FiscalPosition.browse(fpos)
                if not fpos.id :
                    errors.append('fiscal position is not valid for vendor ' + str(input_data['partner_id']))

            po_values = {
                "partner_id": partner.id,
                'dc_id': dc.id,
                'request_id' : requester.id,
                'date_order' : '',
                'schedule_date': '',
                'currency_id': 0,
                'payment_term_id': 0,
                'picking_type_id': picking_type.id if picking_type != '' else '',
                'incoterm_id' : incoterm.id,
                'tfm_doc': (
                    'tfm' if input_data['tfm_doc'] == 'TFM'
                    else 'non_tfm' if input_data['tfm_doc'] == 'NON-TFM'
                    else 'mars'
                ),
                'partner_ref': str(input_data['partner_ref']),
                'is_po_direct': False,
                'fiscal_position_id': fpos.id if fpos != '' else '',
                'order_lines': [],
                'log_doc' : input_data['log_doc'],
                'executed_at': input_data['executed_at']
            }

             # handle payment termn cuman 1 dan 2
            if isinstance(input_data['payment_term'], int):
                if  input_data['payment_term'] not in [1,2]:
                    errors.append('payment_term "' + str(input_data['payment_term']) + '" only valid if 1 or 2.')
                else:
                    if  input_data['payment_term'] == 1:
                        if not partner.property_supplier_payment_term_id:
                            errors.append('property_supplier_payment_term_id is empty for vendor ' + str(input_data['partner_id']))
                        else:
                            po_values['payment_term_id'] = partner.property_supplier_payment_term_id.id
                    elif input_data['payment_term'] == 2:
                        if  not partner.property_supplier_payment_term_id_2 :
                            errors.append('property_supplier_payment_term_id_2 is empty for vendor ' + str(input_data['partner_id']))
                        else :
                            po_values['payment_term_id'] = partner.property_supplier_payment_term_id_2.id

                if not partner.property_purchase_currency_id:
                    errors.append('property_purchase_currency_id is empty for vendor ' + str(input_data['partner_id']))
                else:
                    po_values['currency_id'] = partner.property_purchase_currency_id.id

            # Check if order_date and schedule_date is valid
            EXCEL_EPOCH = datetime(1900, 1, 1)
            try:
                order_date = EXCEL_EPOCH + timedelta(days=input_data['order_date'] - 2)
                po_values['date_order'] = order_date.strftime('%Y-%m-%d %H:%M:%S')
            except KeyError as e:
                errors.append('Missing key in order_date: ' + str(e))
            except Exception as e:
                errors.append('Error parsing order_date:  ' + str(e))

            schedule_date = input_data['schedule_date']
            try:
                schedule_date = EXCEL_EPOCH + timedelta(days=schedule_date - 2)
                po_values['schedule_date'] = schedule_date.strftime('%Y-%m-%d %H:%M:%S')
            except KeyError as e:
                errors.append('Missing key in schedule_date: ' + str(e))
            except Exception as e:
                errors.append('Error parsing schedule_date:  ' + str(e))

            # Validate order_lines
            order_line_keys = {
                'product': str,
                'description': str,
                'account_analytic': str,
                'activity': str,
                'product_qty': int,
                'price': int,
                'taxes': str
            }

            product_name_set = set()
            for line_index, line in enumerate(input_data['order_lines'], start=1):
                for key, expected_type in order_line_keys.items():
                    if key not in line:
                        errors.append("Line " + str(line_index) + ": Missing required key " + key + ".")
                    elif not isinstance(line[key], expected_type):
                        errors.append("Line " + str(line_index) + ": Invalid data type for " + key + ". Expected " + expected_type.__name__ + ".")
                    elif key not in ['activity'] and line[key] in [None, '', [], {}, ' ']:
                        errors.append("Line " + str(line_index) + ": The value for " + key + " cannot be empty.")

                if line.get('product_qty', 0) <= 0:
                    errors.append("Line " + str(line_index) + ": product_qty must be greater than 0.")
                if line.get('price', 0) <= 0:
                    errors.append("Line " + str(line_index) + ": price must be greater than 0.")

                tax = http.request.env['account.tax'].sudo().search([('name', '=', line['taxes'])], limit=1)
                if not tax:
                    errors.append("Line " + str(line_index) + ": Tax " + line['taxes'] + " does not exist in account.tax.")

                product = http.request.env['product.product'].sudo().search([('default_code', '=', line['product'])], limit=1)
                if line['product'] != '' and not product:
                    errors.append("Line " + str(line_index) + ": Product with default code " + line['product'] + " does not exist in product.product.")
                
                product_dupl_val= str(product.id) + line['description'] + line['account_analytic'] # check if an item have same product code, product name, and analytic account                
                if product_dupl_val in product_name_set:
                    for i in po_values['order_lines']:
                        if i['product_id'] == product.id and i['description'] == line['description'] and i['account_analytic_id'] == line['account_analytic']:
                            i['product_qty'] += line['product_qty']
                            break
                    continue # skip all the line after this because product is duplicated

                if product and not product.uom_po_id and not product.uom_id:
                    errors.append("Line " + str(line_index) + ": Product with default code " + line['product'] + " does not have a unit of measure (UoM).")

                account_analytic = http.request.env['account.analytic.account'].sudo().search([('code', '=', line['account_analytic'])], limit=1)
                if line['account_analytic'] != '' and not account_analytic:
                    errors.append("Line " + str(line_index) + ": Account analytic " + line['account_analytic'] + " does not exist in account.analytic.account.")

                order_line = {
                    'product_id' : product.id,
                    'name': product.display_name,
                    'date_planned': schedule_date,
                    'product_uom': product.uom_po_id.id or product.uom_id.id,
                    'price_unit':  line['price'],
                    'product_qty': line['product_qty'],
                    'description': line['description'],
                    'account_analytic_id': line['account_analytic'],
                    'activity_id': '', # selalu kosong kalau dia non-tfm
                    'taxes_id': tax.id
                }
                product_name_set.add(product_dupl_val)

                # Specific validation for 'TFM' and 'MARS'
                if input_data['tfm_doc']  == 'TFM' or input_data['tfm_doc'] == 'MARS':
                    if line['activity'] in [None, '', [], {}, ' ']:
                        errors.append("Line " + str(line_index) + ": The value for activity cannot be empty because tfm_doc is TFM/MARS.")

                    activity = http.request.env['account.tfm.activity'].sudo().search([('name', '=', line['activity'])], limit=1)
                    if not activity:
                        errors.append("Line " + str(line_index) + ": Activity " + line['activity'] + " does not exist in account.tfm.activity.")

                    order_line['activity_id'] = activity.id
                po_values['order_lines'].append(order_line)

            # Return all errors if any
            if errors:
                return {
                    'status': 'error',
                    'message': 'Validation failed',
                    'errors': errors,
                    'data': {
                        'input_data': input_data,
                    },
                }

            # If validation passes
            return {
                'status': 'success',
                'message': 'Validation successful',
                'data': {
                    'input_data': input_data,
                    'transformed_data' : po_values
                },
            }

        except Exception as e:
            return {
                'status': 'error exception',
                'message': 'An exception occurred: ' + str(e),
                'data': {
                    'input_data': raw_data,
                },
            }
