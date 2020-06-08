# Copyright 2017-2019 Akretion France (http://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    import_reconcile = fields.Char(string='Import Reconcile Ref')
    import_external_id = fields.Char(
        help='Can be used to tag imported move.'
             ' Delete all importred move if need (error on file imported)')
