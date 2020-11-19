# Copyright 2017-2020 Akretion France (http://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    import_reconcile = fields.Char(string='Import Reconcile Ref')
    import_external_id = fields.Char(
        help='Can be used to tag imported move. '
             'Can be useful to delete an imported move if needed in case of '
             'error on the imported file.')
