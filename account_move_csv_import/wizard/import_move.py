# -*- coding: utf-8 -*-
# © 2012-2017 Akretion (http://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import unicodecsv
import base64
from tempfile import TemporaryFile
import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


class AccountMoveImport(models.TransientModel):
    _name = "account.move.import"
    _description = "Import account move from CSV file"

    file_to_import = fields.Binary(
        string='File to Import', required=True,
        help="File containing the journal entry(ies) to import.")
    file_format = fields.Selection([
        ('meilleuregestion', 'MeilleureGestion (Prisme)'),
        ('genericcsv', 'Generic CSV'),
        ('quadra', 'Quadra'),
        ('extenso', 'In Extenso'),
        ], string='File Format', required=True,
        help="Select the type of file you are importing.")
    post_move = fields.Boolean(
        string='Validate the Journal Entry',
        help="If True, the journal entry will be posted after the import.")
    force_journal_id = fields.Many2one(
        'account.journal', string="Force Journal",
        help="Journal in which the journal entry will be created, "
        "even if the file indicate another journal.")
    force_move_ref = fields.Char('Force Journal Entry Reference')
    force_move_line_name = fields.Char('Force Journal Items Label')
    force_move_date = fields.Date('Force Journal Entry Date')

    # PIVOT FORMAT
    # [{
    #    'account': {'code': '411000'},
    #    'partner': {'ref': '1242'}, # you can many more keys to match partners
    #    'name': u'label',  # required
    #    'credit': 12.42,
    #    'debit': 0,
    #    'ref': '9804',  # optional
    #    'journal': {'code': 'VT'},
    #    'date': '2017-02-15',  # also accepted in datetime format
    #    'line': 2,  # Line number for error messages.
                     # Must be the line number including headers
    # },
    #  2nd line...
    #  3rd line...
    # ]

    def run_import(self):
        self.ensure_one()
        file_format = self.file_format
        fileobj = TemporaryFile('w+')
        print "file_to_import=", self.file_to_import
        fileobj.write(self.file_to_import.decode('base64'))
        fileobj.seek(0)  # We must start reading from the beginning !
        if file_format == 'meilleuregestion':
            pivot = self.run_import_meilleuregestion()
        elif file_format == 'genericcsv':
            pivot = self.run_import_genericcsv()
        elif file_format == 'quadra':
            pivot = self.run_import_quadra()
        elif file_format == 'extenso':
            pivot = self.run_import_extenso(fileobj)
        else:
            raise UserError(_("You must select a file format."))
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

    def run_import_extenso(self, fileobj):
        fieldnames = [
            'journal', 'date', False, 'account', False, False, False, False,
            'debit', 'credit']
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter='\t',
            quoting=False,
            encoding='utf-8',
            )
        res = []
        i = 0
        for l in reader:
            print "l=", l
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
        from pprint import pprint
        pprint(res)
        return res


    def run_import_genericcsv(self, cr, uid, import_data, context=None):
        setup = {
            'encoding': 'utf-8',
            'delimiter': ',',
            'quotechar': '"',
            'quoting': unicodecsv.QUOTE_MINIMAL,
            'fieldnames': [
                'date', 'journal', 'account',
                'analytic', 'label', 'debit', 'credit',
                ],
            'date_format': '%d/%m/%Y',
            'top_lines_to_skip': 0,
            'bottom_lines_to_skip': 0,
        }
        account_move_dict = self.parse_csv(
            cr, uid, import_data, setup, context=context)
        action = self._generate_account_move(
            cr, uid, account_move_dict, setup, context=context)
        return action

    def run_import_meilleuregestion(self, cr, uid, import_data, context=None):
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
        account_move_dict = self.parse_csv(
            cr, uid, import_data, setup, context=context)
        action = self._generate_account_move(
            cr, uid, account_move_dict, setup, context=context)
        return action

    def run_import_quadra(self, cr, uid, import_data, context=None):
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

        account_move_dict = self.parse_cols(
            cr, uid, import_data, setup, context=context)
        action = self._generate_account_move(
            cr, uid, account_move_dict, setup, context=context)
        return action

    def parse_common(self, cr, uid, import_data, setup, context=None):
        setup['post_move'] = import_data.post_move
        setup['force_journal_id'] = import_data.force_journal_id.id or False
        setup['force_move_ref'] = import_data.force_move_ref or False
        setup['force_move_date'] = import_data.force_move_date or False
        fullstr = base64.decodestring(import_data.file_to_import)
        if setup.get('bottom_lines_to_skip'):
            end_seq = -(setup.get('bottom_lines_to_skip') + 1)
        else:
            end_seq = None
        return fullstr, end_seq

    def _extract_field(self, cr, uid, setup, line, field, context=None):
        return line[
            setup['field_positions'][field][0]:
            setup['field_positions'][field][1] + 1
            ]

    def _extract_analytic_field(
            self, cr, uid, setup, line, field, context=None):
        return line[
            setup['analytic_field_positions'][field][0]:
            setup['analytic_field_positions'][field][1] + 1
            ]

    def parse_cols(self, cr, uid, import_data, setup, context=None):
        _logger.debug('Starting to import flat file')
        fullstr, end_seq = self.parse_common(
            cr, uid, import_data, setup, context=context)
        cutstr = fullstr.split('\n')
        if setup.get('top_lines_to_skip') or setup.get('bottom_lines_to_skip'):
            cutstr = cutstr[setup.get('top_lines_to_skip'):end_seq]
            _logger.debug(
                '%d top lines skipped' % setup.get('top_lines_to_skip'))
            _logger.debug(
                '%d bottom lines skipped' % setup.get('bottom_lines_to_skip'))

        move_tmp = []
        last_move_line = False
        # On the first "round", the amount is copied
        for line in cutstr:
            # This should only be the case for the last line
            # TODO find why and fix
            if not line:
                continue
            line_dict = {}
            if (
                    setup.get('analytic_lines_start_with')
                    and line[0:len(setup.get('analytic_lines_start_with'))] ==
                    setup.get('analytic_lines_start_with')):

                assert last_move_line is not False, \
                    'Analytic lines must be after real move lines'
                ana_account = self._extract_analytic_field(
                    cr, uid, setup, line, 'account', context=context)
                ana_amount_cents = int(self._extract_analytic_field(
                    cr, uid, setup, line, 'amount_cents', context=context))
                if last_move_line['sign'] == 'C':
                    debit = 0
                    credit = float(ana_amount_cents) / 100
                elif last_move_line['sign'] == 'D':
                    credit = 0
                    debit = float(ana_amount_cents) / 100
                # The final move line is created here, using values
                # from the last real move line
                line_dict = {
                    'date': last_move_line['date'],
                    'label': last_move_line['label'],
                    'account': last_move_line['account'],
                    'analytic': ana_account,
                    'credit': credit,
                    'debit': debit,
                    }
                # On the last real move line, we decrement 'work_amount_cents'
                # of the amount of the analytic line
                last_move_line['work_amount_cents'] -= ana_amount_cents
                move_tmp.append(line_dict)
            elif (
                    setup.get('move_lines_start_with')
                    and line[0:len(setup.get('move_lines_start_with'))] ==
                    setup.get('move_lines_start_with')):

                line = line.strip()
                raw_account = self._extract_field(
                    cr, uid, setup, line, 'account', context=context)
                if raw_account.isdigit():
                    if len(raw_account) > 6:
                        line_dict['account'] =\
                            raw_account[0:-(len(raw_account)-6)]
                    elif len(raw_account) == 6:
                        line_dict['account'] = raw_account
                else:
                    line_dict['account'] = raw_account.strip()
                line_dict['date'] = self._extract_field(
                    cr, uid, setup, line, 'date', context=context)
                raw_label = self._extract_field(
                    cr, uid, setup, line, 'label', context=context).strip()
                line_dict['label'] = raw_label.decode(setup.get('encoding'))
                amount_cents = int(
                    self._extract_field(
                        cr, uid, setup, line, 'amount_cents', context=context))
                line_dict['work_amount_cents'] = amount_cents
                line_dict['total_amount_cents'] = amount_cents
                sign = self._extract_field(
                    cr, uid, setup, line, 'sign', context=context)
                assert sign in ('C', 'D'), 'Sign can only be C or D'
                line_dict['sign'] = sign
                line_dict['journal'] = self._extract_field(
                    cr, uid, setup, line, 'journal', context=context)
                line_dict['analytic'] = False
                # print "line_dict=", line_dict
                last_move_line = line_dict
                move_tmp.append(line_dict)
        # print "move=", pformat(move)
        # print "len move=", len(move)
        move = []
        # In this second loop, we update the real move lines that still have
        # a value for 'work_amount_cents'
        # and we remove the real lines for which 'work_amount_cents' = 0
        for line in move_tmp:
            if 'work_amount_cents' in line:
                assert not line.get('analytic'), 'No analytic'
                if line['work_amount_cents']:
                    assert line['work_amount_cents'] == \
                        line['total_amount_cents'], \
                        'Real lines should have analytic lines for the '\
                        'full amount or no analytic lines at all'
                    if line['sign'] == 'C':
                        line['credit'] = float(line['work_amount_cents']) / 100
                        line['debit'] = 0
                    elif line['sign'] == 'D':
                        line['credit'] = 0
                        line['debit'] = float(line['work_amount_cents']) / 100
                else:
                    line = False
            if line:
                move.append(line)
        return move

    def parse_csv(self, cr, uid, import_data, setup, context=None):
        _logger.debug('Starting to import CSV file')
        # Code inspired by module/wizard/base_import_language.py
        fullstr, end_seq = self.parse_common(
            cr, uid, import_data, setup, context=context)
        if setup.get('top_lines_to_skip') or setup.get('bottom_lines_to_skip'):
            cutlist = fullstr.split('\n')[
                setup.get('top_lines_to_skip'):
                end_seq
                ]
            cutstr = '\n'.join(cutlist)
            _logger.debug(
                '%d top lines skipped' % setup.get('top_lines_to_skip'))
            _logger.debug(
                '%d bottom lines skipped' % setup.get('bottom_lines_to_skip'))
        else:
            cutstr = fullstr
        fileobj = TemporaryFile('w+')
        setup['tempfile'] = fileobj
        fileobj.write(cutstr)
        fileobj.seek(0)  # We must start reading from the beginning !
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=setup.get('fieldnames'),
            delimiter=setup.get('delimiter'),
            quoting=setup.get('quoting'),
            quotechar=setup.get('quotechar'),
            encoding=setup.get('encoding', 'utf-8'),
            )
        return reader

    def _generate_account_move(
            self, cr, uid, account_move_dict, setup, context=None):
        line_csv = setup.get('top_lines_to_skip', 0)
        # moves_to_create contains a seq ;
        # each member is a dict with keys journal, date, lines and ref
        moves_to_create = []
        move_ids_created = []
        move_dict_init = {
            'journal': False,
            'date_datetime': False,
            'ref': False,
            'lines': [],
            'balance': 0}
        move_dict = deepcopy(move_dict_init)

        for row in account_move_dict:
            line_csv += 1
            _logger.debug('[line %d] Content : %s' % (line_csv, row))
            # Date and journal are read from the first line
            if setup.get('date_format') and not move_dict['date_datetime']:
                move_dict['date_datetime'] = datetime.strptime(
                    row['date'], setup.get('date_format'))
            if row.get('journal') and not move_dict['journal']:
                move_dict['journal'] = row['journal']
            if not move_dict['ref']:
                move_dict['ref'] = row['label']

            if row.get('analytic'):
                analytic_search = self.pool['account.analytic.account'].search(
                    cr, uid, [('code', '=', row['analytic'])], context=context)
                if len(analytic_search) != 1:
                    raise UserError(
                        _("No match for analytic account code '%s' (line %d "
                            "of the CSV file)")
                        % (row['analytic'], line_csv))
                analytic_account_id = analytic_search[0]
            else:
                analytic_account_id = False
            account_search = self.pool['account.account'].search(
                cr, uid, [('code', '=', row['account'])], context=context)
            if len(account_search) != 1:
                raise UserError(
                    _("No match for legal account code '%s' (line %d of "
                        "the CSV file)")
                    % (row['account'], line_csv))
            account_id = account_search[0]
            try:
                debit = credit = 0
                if row.get('sign'):
                    if setup.get('decimal_separator') == 'coma':
                        amount = float(row['amount'].replace(',', '.'))
                    else:
                        amount = float(row['amount'])
                    if row['sign'].strip() == 'D':
                        debit = amount
                    else:
                        credit = amount
                else:
                    debit = row['debit']
                    credit = row['credit']
                    if debit:
                        if setup.get('decimal_separator') == 'coma':
                            debit = debit.replace(',', '.')
                        debit = float(debit)
                    if credit:
                        if setup.get('decimal_separator') == 'coma':
                            credit = credit.replace(',', '.')
                        credit = float(credit)
            except:
                raise UserError(_(
                    "Check the configuration of the decimal separator "
                    "in the code for this file format import and compare it "
                    "to the 'Debit' and 'Credit' columns."))
            # If debit and credit = 0, we skip the move line
            if not debit and not credit:
                _logger.debug(
                    '[line %d] Skipped because debit=credit=0' % line_csv)
                continue
            line_dict = {
                'account_id': account_id,
                'name': row['label'],
                'debit': debit,
                'credit': credit,
                'analytic_account_id': analytic_account_id,
            }

            move_dict['lines'].append((0, 0, line_dict))
            move_dict['balance'] += debit - credit
            _logger.debug(
                '[line %d] with this line, current balance is %d'
                % (line_csv, move_dict['balance']))
            # print "debit=", debit
            # print "credit=", credit
            # print "move_dict['balance']=", move_dict['balance']
            if not int(move_dict['balance']*100):
                moves_to_create.append(move_dict)
                _logger.debug('[line %d] NEW account move' % line_csv)
                move_dict = deepcopy(move_dict_init)

        if setup.get('tempfile'):
            setup.get('tempfile').close()

        for move_to_create in moves_to_create:
            if setup.get('force_move_date'):
                date_str = setup.get('force_move_date')
            else:
                date_str = datetime.strftime(
                    move_to_create['date_datetime'], '%Y-%m-%d')
            # If the user has forced a journal, we take it
            # otherwize, we take the journal of the CSV file
            if setup.get('force_journal_id'):
                journal_id = setup.get('force_journal_id')
            else:
                journal_search = self.pool['account.journal'].search(
                    cr, uid, [('code', '=', move_to_create['journal'])],
                    context=context)
                if len(journal_search) != 1:
                    raise UserError(
                        _("No match for journal code '%s'")
                        % move_to_create['journal'])
                journal_id = journal_search[0]


            # Select period
            period_search = self.pool['account.period'].find(
                cr, uid, date_str, context=context)
            if len(period_search) != 1:
                raise UserError(
                    _("No matching period for date '%s'") % date_str)
            period_id = period_search[0]

            # Create move
            move_id = self.pool['account.move'].create(cr, uid, {
                'journal_id': journal_id,
                'date': date_str,
                'period_id': period_id,
                'ref': setup.get('force_move_ref') or move_to_create['ref'],
                'line_id': move_to_create['lines'],
                }, context=context)
            _logger.info(
                'Account move ID %d created with %d move lines'
                % (move_id, len(move_to_create['lines'])))
            move_ids_created.append(move_id)

        self.pool['account.move'].validate(
            cr, uid, move_ids_created, context=context)
        _logger.debug('Account move IDs %s validated' % move_ids_created)
        if setup.get('post_move'):
            self.pool['account.move'].post(
                cr, uid, move_ids_created, context=context)
            _logger.debug('Account move ID %s posted' % move_ids_created)


    def create_moves_from_pivot(self, pivot, post=False):
        logger.debug('Final pivot: %s', pivot)
        bdio = self.env['business.document.import']
        amo = self.env['account.move']
        acc_speed_dict = bdio._prepare_account_speed_dict()
        journal_speed_dict = bdio._prepare_journal_speed_dict()
        chatter_msg = []
        # TODO: add line nr in error msg sent by base_business_doc
        # MATCH what needs to be matched... + CHECKS
        for l in pivot:
            assert l.get('line'), 'missing line number'
            if l.get('partner'):
                partner = bdio._match_partner(
                    l['partner'], chatter_msg, partner_type='any')
                l['partner_id'] = partner.id
            else:
                l['partner_id'] = False
            account = bdio._match_account(
                l['account'], chatter_msg, acc_speed_dict)
            l['account_id'] = account.id
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
            cur_balance += l['credit'] - l['debit']
            if (
                    cur_ref == ref and
                    cur_journal_id == l['journal_id'] and
                    cur_date == l['date'] and
                    not float_is_zero(cur_balance, precision_rounding=prec)):
                # append to current move
                cur_move['line_ids'].append((0, 0, self._prepare_move_line(l)))
            else:
                # new move
                if not float_is_zero(cur_balance, precision_rounding=prec):
                    raise UserError(_(
                        "The journal entry that ends on line %d is not "
                        "balanced (balance is %s.") % (l['line'] - 1, cur_balance))
                if cur_move:
                    assert len(cur_move['line_ids']) < 2, 'move should have more than 1 line'
                    moves.append(cur_move)
                # TODO  add _prepare
                cur_move = self._prepare_move(l)
                cur_move['line_ids'] = [(0, 0, self._prepare_move_line(l))]
        if not float_is_zero(cur_balance, precision_rounding=prec):
            raise UserError(_(
                "The journal entry that ends on the last line is not "
                "balanced (balance is %s.") % cur_balance)
        rmoves = self.env['account.move']
        for move in moves:
            rmoves += amo.create(move)
        if post:
            rmoves.post()
        return rmoves

    def _prepare_move(self, pivot_line):
        vals = {
            'journal_id': l['journal_id'],
            'ref': l.get('ref'),
            'date': l['date'],
            }
        return vals

    def _prepare_move_line(self, pivot_line):
        vals = {
            'credit': pivot_line['credit'],
            'debit': pivot_line['debit'],
            'name': pivot_line['name'],
            'partner_id': pivot_line['partner_id'],
            }
        return vals
