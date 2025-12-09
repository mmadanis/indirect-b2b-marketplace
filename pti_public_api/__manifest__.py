{
    'name': 'Odoo Paragon Public API',
    'version': '11.1.0',
    'author': 'PT Paragon Technology and Innovation',
    'license': 'OPL-1',
    'category': 'Tailor-Made',
    'website': 'http: //www.paragon-innovation.com/',
    'summary': 'Custom-built Odoo',
    'description': '''
        This module open api to public access. Business activity that served in this api:\n
        1. Receive customer PO data to create SO.\n
    ''',
    'depends': [
        'account', # python
        # 'sale', # python
    ],
    'data': [
        'views/partner_view.xml',
    ],
    'qweb': [
    ],
    'auto_install': False,
    'installable': True,
    'application': True,
}