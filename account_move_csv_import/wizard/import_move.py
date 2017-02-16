# -*- coding: utf-8 -*-
# © 2012-2017 Akretion (http://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero
from datetime import datetime
import unicodecsv
from tempfile import TemporaryFile
import logging

logger = logging.getLogger(__name__)


class AccountMoveImport(models.TransientModel):
    _name = "account.move.import"
    _description = "Import account move from CSV file"

    file_to_import = fields.Binary(
        string='File to Import', required=True,
        help="File containing the journal entry(ies) to import.")
    file_format = fields.Selection([
        ('genericcsv', 'Generic CSV'),
        # TODO port to v10
        # ('meilleuregestion', 'MeilleureGestion (Prisme)'),
        # ('quadra', 'Quadra'),
        ('extenso', 'In Extenso'),
        ], string='File Format', required=True,
        help="Select the type of file you are importing.")
    post_move = fields.Boolean(
        string='Post Journal Entry',
        help="If True, the journal entry will be posted after the import.")
    force_journal_id = fields.Many2one(
        'account.journal', string="Force Journal",
        help="Journal in which the journal entry will be created, "
        "even if the file indicate another journal.")
    force_move_ref = fields.Char('Force Reference')
    force_move_line_name = fields.Char('Force Label')
    force_move_date = fields.Date('Force Date')

    # PIVOT FORMAT
    # [{
    #    'account': {'code': '411000'},
    #    'analytic': {'code': 'ADM'},
    #    'partner': {'ref': '1242'}, # you can many more keys to match partners
    #    'name': u'label',  # required
    #    'credit': 12.42,
    #    'debit': 0,
    #    'ref': '9804',  # optional
    #    'journal': {'code': 'VT'},
    #    'date': '2017-02-15',  # also accepted in datetime format
    #    'line': 2,  # Line number for error messages.
    #                # Must be the line number including headers
    # },
    #  2nd line...
    #  3rd line...
    # ]

    def file2pivot(self, fileobj):
        file_format = self.file_format
        if file_format == 'meilleuregestion':
            return self.meilleuregestion2pivot(fileobj)
        elif file_format == 'genericcsv':
            return self.genericcsv2pivot(fileobj)
        elif file_format == 'quadra':
            return self.quadra2pivot(fileobj)
        elif file_format == 'extenso':
            return self.extenso2pivot(fileobj)
        else:
            raise UserError(_("You must select a file format."))

    def run_import(self):
        self.ensure_one()
        fileobj = TemporaryFile('w+')
        fileobj.write(self.file_to_import.decode('base64'))
        fileobj.seek(0)  # We must start reading from the beginning !
        pivot = self.file2pivot(fileobj)
        fileobj.close()
        logger.debug('pivot before update: %s', pivot)
        self.update_pivot(pivot)
        moves = self.create_moves_from_pivot(pivot, post=self.post_move)
        action = {
            'name': _('Imported Journal Entries'),
            'res_model': 'account.move',
            'type': 'ir.actions.act_window',
            'nodestroy': False,
            'target': 'current',
            }

        if len(moves) == 1:
            action.update({
                'view_mode': 'form,tree',
                'res_id': moves[0].id,
                })
        else:
            action.update({
                'view_mode': 'tree,form',
                'domain': [('id', 'in', moves.ids)],
                })
        return action

    def update_pivot(self, pivot):
        force_move_date = self.force_move_date
        force_move_ref = self.force_move_ref
        force_move_line_name = self.force_move_line_name
        force_journal = self.force_journal_id or False
        for l in pivot:
            if force_move_date:
                l['date'] = force_move_date
            if force_move_line_name:
                l['name'] = force_move_line_name
            if force_move_ref:
                l['ref'] = force_move_ref
            if force_journal:
                l['journal'] = {'recordset': force_journal}
            if isinstance(l.get('date'), datetime):
                l['date'] = fields.Date.to_string(l['date'])
            if not l['credit']:
                l['credit'] = 0.0
            if not l['debit']:
                l['debit'] = 0.0

    def extenso2pivot(self, fileobj):
        fieldnames = [
            'journal', 'date', False, 'account', False, False, False, False,
            'debit', 'credit']
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter='\t',
            quoting=False,
            encoding='utf-8')
        res = []
        i = 0
        for l in reader:
            i += 1
            l['credit'] = l['credit'] or '0'
            l['debit'] = l['debit'] or '0'
            vals = {
                'journal': {'code': l['journal']},
                'account': {'code': l['account']},
                'credit': float(l['credit'].replace(',', '.')),
                'debit': float(l['debit'].replace(',', '.')),
                'date': datetime.strptime(l['date'], '%d%m%Y'),
                'line': i,
            }
            res.append(vals)
        return res

    def genericcsv2pivot(self, fileobj):
        fieldnames = [
            'date', 'journal', 'account',
            'analytic', 'name', 'debit', 'credit',
            ]
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter=',',
            quotechar='"',
            quoting=unicodecsv.QUOTE_MINIMAL,
            encoding='utf-8')
        res = []
        i = 0
        for l in reader:
            i += 1
            vals = {
                'journal': {'code': l['journal']},
                'account': {'code': l['account']},
                'credit': float(l['credit'] or 0),
                'debit': float(l['debit'] or 0),
                'date': datetime.strptime(l['date'], '%d/%m/%Y'),
                'name': l['name'],
                'line': i,
                }
            if l['analytic']:
                vals['analytic'] = {'code': l['analytic']}
            res.append(vals)
        return res

    def meilleuregestion2pivot(self, fileobj):
        # Prisme
        setup = {
            'encoding': 'latin1',
            'delimiter': ';',
            'quoting': unicodecsv.QUOTE_NONE,
            'fieldnames': [
                'trasha', 'trashb', 'journal', 'trashd', 'trashe',
                'trashf', 'trashg', 'date', 'trashi', 'trashj', 'trashk',
                'trashl', 'trashm', 'trashn', 'account', 'trashp',
                'trashq', 'amount', 'trashs', 'sign', 'trashu',
                'trashv', 'label',
                'trashx', 'trashy', 'trashz', 'trashaa', 'trashab',
                'trashac', 'trashad', 'trashae', 'analytic',
                ],
            'date_format': '%y%m%d',
            'top_lines_to_skip': 1,
            'bottom_lines_to_skip': 0,
            'decimal_separator': 'coma',
        }
        res = []  # TODO
        return res

    def quadra2pivot(self, fileobj):
        setup = {
            'encoding': 'ibm850',
            'date_format': '%d%m%y',
            'top_lines_to_skip': 0,
            'bottom_lines_to_skip': 0,
            'move_lines_start_with': 'M',
            'analytic_lines_start_with': 'I',
            'field_positions': {
                # Indicate position of first char and position of last char
                # First position is 0
                'account': [1, 8],
                'amount_cents': [42, 54],  # amount_cents = amount x 100
                'date': [14, 19],
                'journal': [9, 10],
                'label': [21, 40],
                # 'label': [116, 147],
                'sign': [41, 41],
                },
            'analytic_field_positions': {
                'account': [19, 23],
                'amount_cents': [6, 18],
                },
            }
        res = []
        return res

    def create_moves_from_pivot(self, pivot, post=False):
        logger.debug('Final pivot: %s', pivot)
        bdio = self.env['business.document.import']
        amo = self.env['account.move']
        acc_speed_dict = bdio._prepare_account_speed_dict()
        aacc_speed_dict = bdio._prepare_analytic_account_speed_dict()
        journal_speed_dict = bdio._prepare_journal_speed_dict()
        chatter_msg = []
        # TODO: add line nr in error msg sent by base_business_doc
        # MATCH what needs to be matched... + CHECKS
        for l in pivot:
            assert l.get('line'), 'missing line number'
            account = bdio._match_account(
                l['account'], chatter_msg, acc_speed_dict)
            l['account_id'] = account.id
            if l.get('partner'):
                partner = bdio._match_partner(
                    l['partner'], chatter_msg, partner_type=False)
                l['partner_id'] = partner.commercial_partner_id.id
            if l.get('analytic'):
                analytic = bdio._match_analytic_account(
                    l['analytic'], chatter_msg, aacc_speed_dict)
                l['analytic_account_id'] = analytic.id
            journal = bdio._match_journal(
                l['journal'], chatter_msg, journal_speed_dict)
            l['journal_id'] = journal.id
            if not l.get('name'):
                raise UserError(_(
                    'Line %d: missing label.') % l['line'])
            if not l.get('date'):
                raise UserError(_(
                    'Line %d: missing date.') % l['line'])
            if not isinstance(l.get('credit'), float):
                raise UserError(_(
                    'Line %d: bad value for credit (%s).')
                    % (l['line'], l['credit']))
            if not isinstance(l.get('debit'), float):
                raise UserError(_(
                    'Line %d: bad value for debit (%s).')
                    % (l['line'], l['debit']))
            # test that they don't have both a value
        # EXTRACT MOVES
        moves = []
        cur_journal_id = False
        cur_ref = False
        cur_date = False
        cur_balance = 0.0
        prec = self.env.user.company_id.currency_id.rounding
        cur_move = {}
        for l in pivot:
            ref = l.get('ref', False)
            if (
                    cur_ref == ref and
                    cur_journal_id == l['journal_id'] and
                    cur_date == l['date'] and
                    not float_is_zero(cur_balance, precision_rounding=prec)):
                # append to current move
                cur_move['line_ids'].append((0, 0, self._prepare_move_line(l)))
            else:
                # new move
                if moves and not float_is_zero(
                        cur_balance, precision_rounding=prec):
                    raise UserError(_(
                        "The journal entry that ends on line %d is not "
                        "balanced (balance is %s).")
                        % (l['line'] - 1, cur_balance))
                if cur_move:
                    assert len(cur_move['line_ids']) > 1,\
                        'move should have more than 1 line'
                    moves.append(cur_move)
                cur_move = self._prepare_move(l)
                cur_move['line_ids'] = [(0, 0, self._prepare_move_line(l))]
                cur_date = l['date']
                cur_ref = ref
                cur_journal_id = l['journal_id']
            cur_balance += l['credit'] - l['debit']
        if cur_move:
            moves.append(cur_move)
        if not float_is_zero(cur_balance, precision_rounding=prec):
            raise UserError(_(
                "The journal entry that ends on the last line is not "
                "balanced (balance is %s).") % cur_balance)
        rmoves = self.env['account.move']
        for move in moves:
            rmoves += amo.create(move)
        logger.info(
            'Account moves IDs %s created via file import' % rmoves.ids)
        if post:
            rmoves.post()
        return rmoves

    def _prepare_move(self, pivot_line):
        vals = {
            'journal_id': pivot_line['journal_id'],
            'ref': pivot_line.get('ref'),
            'date': pivot_line['date'],
            }
        return vals

    def _prepare_move_line(self, pivot_line):
        vals = {
            'credit': pivot_line['credit'],
            'debit': pivot_line['debit'],
            'name': pivot_line['name'],
            'partner_id': pivot_line.get('partner_id'),
            'account_id': pivot_line['account_id'],
            'analytic_account_id': pivot_line.get('analytic_account_id'),
            }
        return vals
