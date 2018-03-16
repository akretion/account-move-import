# -*- coding: utf-8 -*-
# © 2018 Akretion,
# @author Mourad EL HADJ MIMOUNE <mourad.elhadj.mimoune@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    import_reconcile = fields.Char()
    import_external_id = fields.Char()