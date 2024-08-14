# -*- coding: utf-8 -*-
{
    'name': "shipping_and_receiving_pickings",

    'summary': """ Validations and restrictions on shipments and receipts of merchandise between warehouses """,

    'description': """ Long description of module's purpose """,

    'author': "gmorillom",
    'maintainer': ['gmorillom'],
    'website': "https://github.com/gmorillom",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/14.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Stock',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': [
        'base',
        'stock'
    ],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/groups.xml',
        'views/views.xml',
    ],
}
