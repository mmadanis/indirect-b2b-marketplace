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


class SaleOrderApi(http.Controller):

    @http.route('/sale/order/', type="json", auth='public', csrf=False, methods=['POST'])
    def ReceiveOrder(self, **kw):
        if not http.request.params or \
            not http.request.httprequest.headers.get('secret',False):
            msg = [{
                'error': {
                    'code': 500,
                    'message': 'Invalid data format'
                }
            }]
            return msg
        # store variable from params
        api_key = http.request.httprequest.headers.get('secret',False)
        origin = http.request.httprequest.headers.get('customer',False)
        # check for secret code and customer ref
        sql = "select id from res_partner where api_key=%s"
        params = (api_key,)
        http.request.cr.execute(sql,params)
        b2b = http.request.cr.fetchall()
        if len(b2b)!=1:
            msg = [{
                'error': {
                    'code': 501,
                    'message': 'Wrong data customer'
                }
            }]
            return msg
        response = []
        for params_att in http.request.params['orders']:
            po_error = False
            dc_name = params_att['dc_dest']
            po_number = params_att['po_number']
            details = params_att['details']
            ref = params_att['cust_id']
            exiration_date = params_att['delivery_date']
            order_date = params_att['order_date']
            # check po has been executed
            sql = "select id,name from sale_order where client_order_ref=%s and state<>%s"
            params = (po_number,'cancel',)
            http.request.cr.execute(sql,params)
            res = http.request.cr.fetchall()
            if res:
                response.append({po_number : {
                    'error': {
                        'code': 201,
                        'message': 'PO {} has been executed with order number {}'.format(po_number,res[0][1])
                    }
                }})
                po_error = True
                continue
            # check id partner
            sql = "select id from res_partner where ref=%s and active=true"
            params = (ref,)
            http.request.cr.execute(sql,params)
            partner = http.request.cr.fetchall()
            if len(partner)!=1:
                response.append({po_number : {
                    'error': {
                        'code': 501,
                        'message': 'Wrond data customer ref: {}'.format(ref)
                    }
                }})
                po_error = True
                partner_id = '0'
            else :
                partner_id = partner[0][0]
            sql = "select id, warehouse_id from res_partner where name=%s and is_dc=%s and active=true"
            params = (dc_name,True)
            http.request.cr.execute(sql,params)
            dc = http.request.cr.fetchall()
            if len(dc)!=1:
                response.append({po_number : {
                    'error': {
                        'code': 502,
                        'message': 'Wrond data customer DC : {}'.format(dc_name)
                    }
                }})
                po_error = True
                dc_id = 0
                warehouse_id = 0
            else :
                dc_id, warehouse_id = dc[0]
            order_data = {
                'partner_id': partner_id,
                'dc_id': dc_id,
                'warehouse_id': warehouse_id,
                'client_order_ref': po_number,
                'origin': origin,
                'validity_date' : exiration_date,
                'date_order' : order_date,
                'order_line': []
            }
            for item in details:
                sql = """
                    select pp.id
                    from product_product pp
                    inner join product_template pt on pp.product_tmpl_id=pt.id
                    where pt.default_code=%s and
                    pp.active = true
                """
                params = (item['item_code'],)
                http.request.cr.execute(sql,params)
                res = http.request.cr.fetchall()
                if len(res)!=1:
                    response.append({po_number : {
                        'error': {
                            'code': 503,
                            'message': 'Wrond data product: {}'.format(item['item_code'])
                        }
                    }})
                    po_error = True
                    prod_id = 0
                else :
                    prod_id = res[0][0]
                order_data['order_line'].append((0,0,{
                    'product_id': prod_id,
                    'product_uom_qty': item['quantity']
                }))
            if po_error == False :
                sql = "select id from res_users where login=%s"
                params = (user_system,)
                http.request.cr.execute(sql,params)
                user_id = http.request.cr.fetchall()
                user_id = user_id[0][0]
                so = http.request.env['sale.order'].sudo(user_id).create(order_data)
                so.onchange_partner_id()
                so.apply_discount()
                # so.action_confirm()
                msg = """
                    This order generated from Odoo API.
                """
                so.sudo(user_id).message_post(body=msg,
                    message_type='comment',
                    subtype='mt_comment')
                response.append({po_number : {
                        'response': 'Order accepted well, please refer this order number to confirm.',
                        'order number': so.name
                        }
                    })
        return response