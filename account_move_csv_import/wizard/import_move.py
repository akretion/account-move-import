# -*- encoding: utf-8 -*-
##############################################################################
#
#    Account move CSV import module for OpenERP
#    Copyright (C) 2012-2014 Akretion (http://www.akretion.com)
#    @author Alexis de Lattre <alexis.delattre@akretion.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields
from openerp.tools.translate import _
from datetime import datetime
import unicodecsv
import base64
from tempfile import TemporaryFile
import logging
from copy import deepcopy

_logger = logging.getLogger(__name__)


class account_move_import(orm.TransientModel):
    _name = "account.move.import"
    _description = "Import account move from CSV file"

    def run_import(self, cr, uid, ids, context=None):
        import_data = self.browse(cr, uid, ids[0], context=context)
        file_format = import_data.file_format
        if file_format == 'meilleuregestion':
            return self.run_import_meilleuregestion(
                cr, uid, import_data, context=context)
        elif file_format == 'genericcsv':
            return self.run_import_genericcsv(
                cr, uid, import_data, context=context)
        elif file_format == 'quadra':
            return self.run_import_quadra(
                cr, uid, import_data, context=context)
        else:
            raise orm.except_orm(
                _('Error :'),
                _("You must select a file format."))

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
        setup = {
            'encoding': 'latin1',
            'delimiter': ';',
            'quoting': unicodecsv.QUOTE_NONE,
            'fieldnames': [
                'trash1', 'trash2', 'trash3', 'trash4', 'trash5', 'account',
                'date', 'trash6', 'analytic', 'trash7', 'trash8', 'trash9',
                'journal', 'label', 'label2', 'sign', 'amount', 'debit',
                'credit',
                ],
            'date_format': '%d/%m/%Y',
            'top_lines_to_skip': 4,
            'bottom_lines_to_skip': 3,
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
            print "line=", line
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
                print "APPEND ANA line_dict=", line_dict
                move_tmp.append(line_dict)
            elif (
                    setup.get('move_lines_start_with')
                    and line[0:len(setup.get('move_lines_start_with'))] ==
                    setup.get('move_lines_start_with')):

                line = line.strip()
                print "line=", line
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
        reader = unicodecsv.reader(
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
            if not move_dict['date_datetime']:
                move_dict['date_datetime'] = datetime.strptime(
                    row['date'], setup.get('date_format'))
            if not move_dict['journal']:
                move_dict['journal'] = row['journal']
            if not move_dict['ref']:
                move_dict['ref'] = row['label']

            if row['analytic']:
                analytic_search = self.pool['account.analytic.account'].search(
                    cr, uid, [('code', '=', row['analytic'])], context=context)
                if len(analytic_search) != 1:
                    raise orm.except_orm(
                        _('Error :'),
                        _("No match for analytic account code '%s' (line %d "
                            "of the CSV file)")
                        % (row['analytic'], line_csv))
                analytic_account_id = analytic_search[0]
            else:
                analytic_account_id = False
            account_search = self.pool['account.account'].search(
                cr, uid, [('code', '=', row['account'])], context=context)
            if len(account_search) != 1:
                raise orm.except_orm(
                    _('Error:'),
                    _("No match for legal account code '%s' (line %d of "
                        "the CSV file)")
                    % (row['account'], line_csv))
            account_id = account_search[0]
            try:
                if row['debit']:
                    debit = float(row['debit'])
                else:
                    debit = 0
                if row['credit']:
                    credit = float(row['credit'])
                else:
                    credit = 0
            except:
                raise orm.except_orm(
                    _('Error:'),
                    _("Check that the decimal separator for the 'Debit' and "
                        "'Credit' columns is a dot"))
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
                    raise orm.except_orm(
                        _('Error:'),
                        _("No match for journal code '%s'")
                        % move_to_create['journal'])
                journal_id = journal_search[0]

            # Select period
            period_search = self.pool['account.period'].find(
                cr, uid, date_str, context=context)
            if len(period_search) != 1:
                raise orm.except_orm(
                    _('Error :'),
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
            _logger.debug(
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

        action = {
            'name': _('Account Move'),
            'res_model': 'account.move',
            'type': 'ir.actions.act_window',
            'nodestroy': False,
            'target': 'current',
            'context': context,
            }

        if len(move_ids_created) == 1:
            action.update({
                'view_mode': 'form,tree',
                'res_id': move_ids_created[0],
                })
        else:
            action.update({
                'view_mode': 'tree,form',
                'domain': [('id', 'in', move_ids_created)],
                })
        return action

    _columns = {
        'file_to_import': fields.binary(
            'File to Import', required=True,
            help="CSV file containing the account move to import."),
        'file_format': fields.selection([
            ('meilleuregestion', 'MeilleureGestion'),
            ('genericcsv', 'Generic CSV'),
            ('quadra', 'Quadra'),
            ], 'File Format', required=True,
            help="Select the type of file you are importing."),
        'post_move': fields.boolean(
            'Validate the Account Move',
            help="If True, the account move will be posted after the import."),
        'force_journal_id': fields.many2one(
            'account.journal', string="Force Journal",
            help="Journal in which the account move will be created, "
            "even if the CSV file indicate another journal."),
        'force_move_ref': fields.char('Force Move Reference'),
    }
