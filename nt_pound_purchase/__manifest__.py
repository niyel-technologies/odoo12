# -*- coding: utf-8 -*-
{
    'name': "NT Pound Purchase",
    'summary': """""",
    'description': """""",
    'author': "Niyel Technologies",
    'website': "http://www.niyel-technologies.com",
    'category': 'Purchases',
    'version': '12.0.1.0.0',
    'depends': ['purchase', 'pound_product'],
    'data': [
        # 'security/ir.model.access.csv',
        'views/product_view.xml',
        'views/purchase_view.xml',
        'wizard/purchase_order_wizard_view.xml',
    ],
}