# Copyright 2020 Stein & Gabelgaard ApS
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMoveImportMapItem(models.Model):

    _name = 'account.move.import.map.item'
    _description = 'Account Move Import Map Item'

    name = fields.Char('Source Account')
    account_id = fields.Many2one('account.account', 'Destination Account')
    map_id = fields.Many2one('account.move.import.map', 'Account Mapping')
    company_id = fields.Many2one('res.company', 'Company', related='map_id.company_id', readonly=True, store=True)
