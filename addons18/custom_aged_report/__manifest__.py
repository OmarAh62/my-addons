{
    'name': 'Custom Aged Partner Balance',
    'version': '18.0.1.0.4',
    'category': 'Accounting',
    'author': 'Omar Ahmed',
    'depends': ['account_accountant', 'account_reports'],
    'data': [
        'views/aged_partner_balance_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_aged_report/static/src/css/ged_partner_balance_filters.css',
            'custom_aged_report/static/src/js/sales_person_filters.js',
            'custom_aged_report/static/src/xml/aged_partner_balance_filters.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
