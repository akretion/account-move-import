# Copyright 2020 Stein & Gabelgaard ApS
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMoveImportColMap(models.Model):

    _name = 'account.move.import.col.map'
    _description = 'Account Move Import Col Map'  # TODO

    name = fields.Char()
    has_header = fields.Boolean('Import file has header in first line')
    skip_lines = fields.Integer('Skip top lines')
    date_fld = fields.Char('Date field', help="Date field header or Column ('A' to 'Z')")
    date_format = fields.Char('Date format', default='%d-%m-%Y')
    account_fld = fields.Char('Account field', help="Account field header or Column ('A' to 'Z')")
    voucher_fld = fields.Char('Voucher field', help="Voucher field header or Column ('A' to 'Z')")
    text_fld = fields.Char('Text field', help="Voucher field header or Column ('A' to 'Z')")
    amount_fld = fields.Char('Amount field', help="Amount field header or Column ('A' to 'Z') - with sign")
    debit_fld = fields.Char('Debit field', help="Debit field header or Column ('A' to 'Z')")
    debit_fld = fields.Char('Debit field', help="Debit field header or Column ('A' to 'Z')")
    credit_fld = fields.Char('Credit field', help="Debit field header or Column ('A' to 'Z')")
    delimiter = fields.Char('Delimiter', default=',')
    encoding = fields.Char('Encoding', default='utf-8')
