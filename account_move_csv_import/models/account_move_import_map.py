# Copyright 2020 Stein & Gabelgaard ApS
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMoveImportMap(models.Model):

    _name = 'account.move.import.map'
    _description = 'Account Move Import Map'

    name = fields.Char()
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        change_default=True,
        required=True,
        default=lambda self: self.env["res.company"]._company_default_get(
            "account.move.import.map"
        ),
    )
    item_ids = fields.One2many('account.move.import.map.item', 'map_id', 'Account mappings')

    def _prepare_account_speed_dict(self):
        speed_dict = {}
        for l in self.item_ids:
            speed_dict[l.name] = l.account_id.id
        return speed_dict
