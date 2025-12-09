{
    'name': 'PTI Purchase Order',
    'website': 'http://paragon-technology.com',
    'author': 'Khoerurrizal',
    'version': '1.1',
    'category': 'Purchase',
    'summary': 'Patch all purchase feature',
    'description': """

    """,
    'depends': ['pti_branch_dc','purchase', 'web', 'pti_purchase_requisition', 'pti_product_supplier', 'sale_discounts'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/ir.rule.xml',
        'views/template_print_po.xml',
        'views/purchase_order_report.xml',
        'views/po_header.xml',
        'views/quick_po.xml',
        'views/stock_picking.xml',
        'views/general_description.xml',
        'views/res_partner_views.xml',
        'views/product_template.xml',
        'views/purchase_order_view.xml',
        'views/stock_return_picking.xml',
        'views/purchase_order_recap.xml',
        'security/security.xml',
        'wizard/purchase_order_wizard.xml',
        'wizard/purchase_order_indirect.xml'
    ],
    'installable': True,
    'auto_install': False,
}
