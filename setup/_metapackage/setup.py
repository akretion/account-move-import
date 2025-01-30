import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo-addons-akretion-account-move-import",
    description="Meta package for akretion-account-move-import Odoo addons",
    version=version,
    install_requires=[
        'odoo-addon-account_move_csv_import>=16.0dev,<16.1dev',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 16.0',
    ]
)
