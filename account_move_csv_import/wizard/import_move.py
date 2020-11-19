# Copyright 2012-2020 Akretion France (http://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, date as datelib
import unicodecsv
from tempfile import TemporaryFile
import base64
import logging

logger = logging.getLogger(__name__)
try:
    import xlrd
except ImportError:
    logger.debug('Cannot import xlrd')

GENERIC_CSV_DEFAULT_DATE = '%d/%m/%Y'


class AccountMoveImport(models.TransientModel):
    _name = "account.move.import"
    _description = "Import account move from CSV file"

    file_to_import = fields.Binary(
        string='File to Import', required=True,
        help="File containing the journal entry(ies) to import.")
    filename = fields.Char()
    file_format = fields.Selection([
        ('genericcsv', 'Generic CSV'),
        ('fec_txt', 'FEC (text)'),
        ('nibelis', 'Nibelis (Prisme)'),
        ('quadra', 'Quadra (without analytic)'),
        ('extenso', 'In Extenso'),
        ('cielpaye', 'Ciel Paye'),
        ('payfit', 'Payfit'),
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
    file_encoding = fields.Selection([
        ('ascii', 'ASCII'),
        ('latin1', 'ISO 8859-15 (alias Latin1)'),
        ('utf-8', 'UTF-8'),
        ], string='File Encoding', default='utf-8')
    # technical fields
    force_move_date_required = fields.Boolean('Force Date Required')
    force_move_line_name_required = fields.Boolean('Force Label Required')
    force_journal_required = fields.Boolean('Force Journal Required')
    advanced_options = fields.Boolean()
    # START GENERIC advanced options
    move_ref_unique = fields.Boolean(
        string='Is move ref unique ?',
        help="If True, ref is used to detect new move in file.")
    force_move_number = fields.Boolean(
        help="If True, ref is used to force acount entry number."
             "This option can be used the save invoice number from"
             " an other accountng software in case you change it to odoo")
    date_by_move_line = fields.Boolean(
        string='Is date by move line ?',
        help="If True, we dont't use date to detecte the lines"
        "of account move. In odoo date are on account move.")
    # START advanced options used in 'genericcsv' import
    # (but could be used by other imports if needed)
    date_format = fields.Char(
        default=GENERIC_CSV_DEFAULT_DATE,
        required=True,
        help='Date format is applicable only on Generic csv file ex "%d%m%Y"')
    file_with_header = fields.Boolean(
        help="Indicate if file contain a headers or not.")

    @api.onchange('file_format')
    def file_format_change(self):
        if self.file_format == 'payfit':
            self.force_move_date_required = True
            self.force_move_line_name_required = True
            self.force_journal_required = True
        else:
            self.force_move_date_required = False
            self.force_move_line_name_required = False
            self.force_journal_required = False

    @api.onchange('move_ref_unique')
    def file_format_change(self):
        if not self.move_ref_unique:
            # we can't force move number if ref is not unique
            self.force_move_number = False

    @api.onchange('advanced_options')
    def advanced_options_change(self):
        if not self.advanced_options:
            self.move_ref_unique = False
            self.force_move_number = False
            self.date_by_move_line = False
            self.date_format = GENERIC_CSV_DEFAULT_DATE
            self.file_with_header = False

    # PIVOT FORMAT
    # [{
    #    'account': '411000',
    #    'analytic': 'ADM',  # analytic account code
    #    'partner': 'R1242',
    #    'name': u'label',  # required
    #    'credit': 12.42,
    #    'debit': 0,
    #    'ref': '9804',  # optional
    #    'journal': 'VT',  # journal code
    #    'date': '2017-02-15',  # also accepted in datetime format
    #    'ref: 'X12',
    #    'reconcile_ref': 'A1242',  # will be written in import_reconcile
    #                               # and be processed after move line creation
    #    'line': 2,  # Line number for error messages.
    #                # Must be the line number including headers
    # },
    #  2nd line...
    #  3rd line...
    # ]

    def file2pivot(self, fileobj, file_bytes):
        file_format = self.file_format
        if file_format == 'nibelis':
            return self.nibelis2pivot(fileobj)
        elif file_format == 'genericcsv':
            return self.genericcsv2pivot(fileobj)
        elif file_format == 'quadra':
            return self.quadra2pivot(file_bytes)
        elif file_format == 'extenso':
            return self.extenso2pivot(fileobj)
        elif file_format == 'payfit':
            return self.payfit2pivot(file_bytes)
        elif file_format == 'cielpaye':
            return self.cielpaye2pivot(fileobj)
        elif file_format == 'fec_txt':
            return self.fectxt2pivot(fileobj)
        else:
            raise UserError(_("You must select a file format."))

    def run_import(self):
        self.ensure_one()
        fileobj = TemporaryFile('wb+')
        file_bytes = base64.b64decode(self.file_to_import)
        fileobj.write(file_bytes)
        fileobj.seek(0)  # We must start reading from the beginning !
        pivot = self.file2pivot(fileobj, file_bytes)
        fileobj.close()
        logger.debug('pivot before update: %s', pivot)
        self.clean_strip_pivot(pivot)
        self.update_pivot(pivot)
        moves = self.create_moves_from_pivot(pivot, post=self.post_move)
        self.reconcile_move_lines(moves)
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

    def clean_strip_pivot(self, pivot):
        for l in pivot:
            for key, value in l.items():
                if value:
                    if isinstance(value, str):
                        l[key] = value.strip() or False
                else:
                    l[key] = False

    def update_pivot(self, pivot):
        force_move_date = self.force_move_date
        force_move_ref = self.force_move_ref
        force_move_line_name = self.force_move_line_name
        force_journal_code =\
            self.force_journal_id and self.force_journal_id.code or False
        for l in pivot:
            if force_move_date:
                l['date'] = force_move_date
            if force_move_line_name:
                l['name'] = force_move_line_name
            if force_move_ref:
                l['ref'] = force_move_ref
            if force_journal_code:
                l['journal'] = force_journal_code
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
                'journal': l['journal'],
                'account': l['account'],
                'credit': float(l['credit'].replace(',', '.')),
                'debit': float(l['debit'].replace(',', '.')),
                'date': datetime.strptime(l['date'], '%d%m%Y'),
                'line': i,
            }
            res.append(vals)
        return res

    def cielpaye2pivot(self, fileobj):
        fieldnames = [
            False, 'journal', 'date', 'account', False, 'amount', 'sign',
            False, 'name', False]
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter='\t',
            quoting=unicodecsv.QUOTE_MINIMAL,
            encoding='utf-8')
        res = []
        i = 0
        for l in reader:
            i += 1
            # skip non-move lines
            if l.get('date') and l.get('name') and l.get('amount'):
                amount = float(l['amount'].replace(',', '.'))
                vals = {
                    'journal': l['journal'],
                    'account': l['account'],
                    'credit': l['sign'] == 'C' and amount or 0,
                    'debit': l['sign'] == 'D' and amount or 0,
                    'date': datetime.strptime(l['date'], '%d/%m/%Y'),
                    'name': l['name'],
                    'line': i,
                }
                res.append(vals)
        return res

    def fectxt2pivot(self, fileobj):
        fieldnames = [
            'journal',        # JournalCode
            False,            # JournalLib
            False,            # EcritureNum
            'date',           # EcritureDate
            'account',        # CompteNum
            False,            # CompteLib
            'partner_ref',    # CompAuxNum
            False,            # CompAuxLib
            'ref',            # PieceRef
            False,            # PieceDate
            'name',           # EcritureLib
            'debit',          # Debit
            'credit',         # Credit
            'reconcile_ref',  # EcritureLet
            False,            # DateLet
            False,            # ValidDate
            False,            # Montantdevise
            False,            # Idevise
            ]
        first_line = fileobj.readline().decode()
        dialect = unicodecsv.Sniffer().sniff(first_line, delimiters="|\t")
        fileobj.seek(0)
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter=dialect.delimiter,
            encoding=self.file_encoding)
        res = []
        i = 0
        for l in reader:
            i += 1
            # Skip header line
            if i == 1:
                continue
            l['credit'] = l['credit'] or '0'
            l['debit'] = l['debit'] or '0'
            vals = {
                'journal': l['journal'],
                'account': l['account'],
                'partner': l['partner_ref'],
                'credit': float(l['credit'].replace(',', '.')),
                'debit': float(l['debit'].replace(',', '.')),
                'date': datetime.strptime(l['date'], '%Y%m%d'),
                'name': l['name'],
                'ref': l['ref'],
                'reconcile_ref': l['reconcile_ref'],
                'line': i,
            }
            res.append(vals)
        return res

    def genericcsv2pivot(self, fileobj):
        # Prisme
        fieldnames = [
            'date', 'journal', 'account', 'partner',
            'analytic', 'name', 'debit', 'credit',
            'ref', 'reconcile_ref'
            ]
        first_line = fileobj.readline().decode()
        dialect = unicodecsv.Sniffer().sniff(first_line)
        fileobj.seek(0)
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter=dialect.delimiter,
            quotechar='"',
            quoting=unicodecsv.QUOTE_MINIMAL,
            encoding='utf-8')
        res = []
        i = 0
        for l in reader:
            i += 1
            if i == 1 and self.file_with_header:
                continue
            date_str = l['date']
            try:
                date = datetime.strptime(date_str, self.date_format)
            except Exception:
                raise UserError(
                    (_("time data : '%s' in line %s does not match format '%s")
                     ) % (date_str, i, self.date_format))

            vals = {
                'journal': l['journal'],
                'account': l['account'],
                'credit': float(l['credit'].replace(',', '.') or 0),
                'debit': float(l['debit'].replace(',', '.') or 0),
                'date': date,
                'name': l['name'],
                'ref': l.get('ref', ''),
                'reconcile_ref': l.get('reconcile_ref', ''),
                'line': i,
                }
            if l['analytic']:
                vals['analytic'] = l['analytic']
            if l['partner']:
                vals['partner'] = l['partner']
            res.append(vals)
        return res

    def nibelis2pivot(self, fileobj):
        fieldnames = [
            'trasha', 'trashb', 'journal', 'trashd', 'trashe',
            'trashf', 'trashg', 'date', 'trashi', 'trashj', 'trashk',
            'trashl', 'trashm', 'trashn', 'account', 'trashp',
            'trashq', 'amount', 'trashs', 'sign', 'trashu',
            'trashv', 'name',
            'trashx', 'trashy', 'trashz', 'trashaa', 'trashab',
            'trashac', 'trashad', 'trashae', 'analytic']
        reader = unicodecsv.DictReader(
            fileobj,
            fieldnames=fieldnames,
            delimiter=';',
            quoting=False,
            encoding='latin1')
        res = []
        i = 0
        for l in reader:
            i += 1
            if i == 1:
                continue
            amount = float(l['amount'].replace(',', '.'))
            credit = l['sign'] == 'C' and amount or False
            debit = l['sign'] == 'D' and amount or False
            vals = {
                'journal': l['journal'],
                'account': l['account'],
                'credit': credit,
                'debit': debit,
                'date': datetime.strptime(l['date'], '%y%m%d'),
                'name': l['name'],
                'line': i,
            }
            if l.get('analytic'):
                vals['analytic'] = l['analytic']
            res.append(vals)
        return res

    def quadra2pivot(self, file_bytes):
        i = 0
        res = []
        file_str = file_bytes.decode(self.file_encoding)
        for l in file_str.split('\n'):
            i += 1
            if len(l) < 54:
                continue
            if l[0] == 'M' and l[41] in ('C', 'D'):
                amount_cents = int(l[42:55])
                amount = amount_cents / 100.0
                vals = {
                    'journal': l[9:11],
                    'account': l[1:9],
                    'credit': l[41] == 'C' and amount or False,
                    'debit': l[41] == 'D' and amount or False,
                    'date': datetime.strptime(l[14:20], '%d%m%y'),
                    'name': l[21:41],
                    'line': i,
                }
                res.append(vals)
        return res

    def payfit2pivot(self, file_bytes):
        wb = xlrd.open_workbook(file_contents=file_bytes)
        sh1 = wb.sheet_by_index(1)
        i = 0
        res = []
        name = u'Paye'
        for rownum in range(sh1.nrows):
            row = sh1.row_values(rownum)
            i += 1
            if i == 1:
                continue
            if not row[0]:
                continue
            account = str(row[0])
            if '.' in account:
                account = account.split('.')[0]
            if not account[0].isdigit():
                continue
            analytic = str(row[3])
            vals = {
                'account': account,
                'name': name,
                'debit': float(row[5] or 0.0),
                'credit': float(row[6] or 0.0),
                'line': i,
            }
            if analytic:
                vals['analytic'] = analytic
            res.append(vals)
        return res

    def _partner_speed_dict(self):
        partner_speed_dict = {}
        company_id = self.env.company.id
        partner_sr = self.env['res.partner'].search_read(
            [
                '|',
                ('company_id', '=', company_id),
                ('company_id', '=', False),
                ('ref', '!=', False),
                ('parent_id', '=', False),
            ],
            ['ref'])
        for l in partner_sr:
            partner_speed_dict[l['ref'].upper()] = l['id']
        return partner_speed_dict

    def create_moves_from_pivot(self, pivot, post=False):
        logger.debug('Final pivot: %s', pivot)
        amo = self.env['account.move']
        company_id = self.env.company.id
        # Generate SPEED DICTS
        acc_speed_dict = {}
        acc_sr = self.env['account.account'].search_read([
            ('company_id', '=', company_id),
            ('deprecated', '=', False)], ['code'])
        for l in acc_sr:
            acc_speed_dict[l['code'].upper()] = l['id']
        aacc_speed_dict = {}
        aacc_sr = self.env['account.analytic.account'].search_read(
            [('company_id', '=', company_id), ('code', '!=', False)],
            ['code'])
        for l in aacc_sr:
            aacc_speed_dict[l['code'].upper()] = l['id']
        journal_speed_dict = {}
        journal_sr = self.env['account.journal'].search_read([
            ('company_id', '=', company_id)], ['code'])
        for l in journal_sr:
            journal_speed_dict[l['code'].upper()] = l['id']
        partner_speed_dict = self._partner_speed_dict()
        key2label = {
            'journal': _('journal codes'),
            'account': _('account codes'),
            'partner': _('partner reference'),
            'analytic': _('analytic codes'),
            }
        errors = {'other': []}
        for key in key2label.keys():
            errors[key] = {}
        # MATCHES + CHECKS
        for l in pivot:
            assert l.get('line') and isinstance(l.get('line'), int),\
                'missing line number'
            if l['account'] in acc_speed_dict:
                l['account_id'] = acc_speed_dict[l['account']]
            if not l.get('account_id'):
                # Match when import = 61100000 and Odoo has 611000
                acc_code_tmp = l['account']
                while acc_code_tmp and acc_code_tmp[-1] == '0':
                    acc_code_tmp = acc_code_tmp[:-1]
                    if acc_code_tmp and acc_code_tmp in acc_speed_dict:
                        l['account_id'] = acc_speed_dict[acc_code_tmp]
                        break
            if not l.get('account_id'):
                # Match when import = 611000 and Odoo has 611000XX
                for code, account_id in acc_speed_dict.items():
                    if code.startswith(l['account']):
                        logger.warning(
                            "Approximate match: import account %s has been matched "
                            "with Odoo account %s" % (l['account'], code))
                        l['account_id'] = account_id
                        break
            if not l.get('account_id'):
                errors['account'].setdefault(l['account'], []).append(l['line'])
            if l.get('partner'):
                if l['partner'] in partner_speed_dict:
                    l['partner_id'] = partner_speed_dict[l['partner']]
                else:
                    errors['partner'].setdefault(l['partner'], []).append(l['line'])
            if l.get('analytic'):
                if l['analytic'] in aacc_speed_dict:
                    l['analytic_account_id'] = aacc_speed_dict[l['analytic']]
                else:
                    errors['analytic'].setdefault(l['analytic'], []).append(l['line'])
            if l['journal'] in journal_speed_dict:
                l['journal_id'] = journal_speed_dict[l['journal']]
            else:
                errors['journal'].setdefault(l['journal'], []).append(l['line'])
            if not l.get('name'):
                errors['other'].append(_('Line %d: missing label.') % l['line'])
            if not l.get('date'):
                errors['other'].append(_(
                    'Line %d: missing date.') % l['line'])
            else:
                if not isinstance(l.get('date'), datelib):
                    try:
                        l['date'] = datetime.strptime(l['date'], '%Y-%m-%d')
                    except Exception:
                        errors['other'].append(_(
                            'Line %d: bad date format %s') % (l['line'], l['date']))
            if not isinstance(l.get('credit'), float):
                errors['other'].append(_(
                    'Line %d: bad value for credit (%s).')
                    % (l['line'], l['credit']))
            if not isinstance(l.get('debit'), float):
                errors['other'].append(_(
                    'Line %d: bad value for debit (%s).')
                    % (l['line'], l['debit']))
            # test that they don't have both a value
        # LIST OF ERRORS
        msg = ''
        for key, label in key2label.items():
            if errors[key]:
                msg += _("List of %s that don't exist in Odoo:\n%s\n\n") % (
                    label,
                    '\n'.join([
                        '- %s : line(s) %s' % (code, ', '.join([str(i) for i in lines]))
                        for (code, lines) in errors[key].items()]))
        if errors['other']:
            msg += _('List of misc errors:\n%s') % (
                '\n'.join(['- %s' % e for e in errors['other']]))
        if msg:
            raise UserError(msg)
        # EXTRACT MOVES
        moves = []
        cur_journal_id = False
        cur_ref = False
        cur_date = False
        cur_balance = 0.0
        comp_cur = self.env.company.currency_id
        seq = self.env['ir.sequence'].next_by_code('account.move.import')
        cur_move = {}
        for l in pivot:
            ref = l.get('ref', False)
            same_move = [
                cur_journal_id == l['journal_id'],
                not comp_cur.is_zero(cur_balance)]
            if not self.date_by_move_line:
                same_move.append(cur_date == l['date'])
            if self.move_ref_unique:
                same_move.append(cur_ref == ref)
            if all(same_move):
                # append to current move
                cur_move['line_ids'].append((0, 0, self._prepare_move_line(l, seq)))
            else:
                # new move
                if moves and not comp_cur.is_zero(cur_balance):
                    raise UserError(_(
                        "The journal entry that ends on line %d is not "
                        "balanced (balance is %s).")
                        % (l['line'] - 1, cur_balance))
                if cur_move:
                    if len(cur_move['line_ids']) <= 1:
                        raise UserError(_(
                            "move should have more than 1 line num: %s,"
                            "data : %s") % (l['line'], cur_move['line_ids']))
                    moves.append(cur_move)
                cur_move = self._prepare_move(l)
                cur_move['line_ids'] = [(0, 0, self._prepare_move_line(l, seq))]
                cur_date = l['date']
                cur_ref = ref
                cur_journal_id = l['journal_id']
            cur_balance += l['credit'] - l['debit']
        if cur_move:
            moves.append(cur_move)
        if not comp_cur.is_zero(cur_balance):
            raise UserError(_(
                "The journal entry that ends on the last line is not "
                "balanced (balance is %s).") % cur_balance)
        rmoves = self.env['account.move']
        for move in moves:
            rmoves += amo.create(move)
        logger.info(
            'Account moves IDs %s created via file import' % rmoves.ids)
        if post:
            rmoves.action_post()
        return rmoves

    def _prepare_move(self, pivot_line):
        vals = {
            'journal_id': pivot_line['journal_id'],
            'ref': pivot_line.get('ref'),
            'date': pivot_line['date'],
            }
        if self.force_move_number and pivot_line.get('ref'):
            vals['name'] = pivot_line.get('ref')
        return vals

    def _prepare_move_line(self, pivot_line, sequence):
        vals = {
            'credit': pivot_line['credit'],
            'debit': pivot_line['debit'],
            'name': pivot_line['name'],
            'partner_id': pivot_line.get('partner_id'),
            'account_id': pivot_line['account_id'],
            'analytic_account_id': pivot_line.get('analytic_account_id'),
            'import_reconcile': pivot_line.get('reconcile_ref'),
            'import_external_id': '%s-%s' % (sequence, pivot_line.get('line')),
            }
        return vals

    def reconcile_move_lines(self, moves):
        comp_cur = self.env.company.currency_id
        logger.info('Start to reconcile imported moves')
        lines = self.env['account.move.line'].search([
            ('move_id', 'in', moves.ids),
            ('import_reconcile', '!=', False),
            ])
        torec = {}  # key = reconcile mark, value = movelines_recordset
        for line in lines:
            if line.import_reconcile in torec:
                torec[line.import_reconcile] |= line
            else:
                torec[line.import_reconcile] = line
        for rec_ref, lines_to_rec in torec.items():
            if len(lines_to_rec) < 2:
                logger.warning(
                    "Skip reconcile of ref '%s' because "
                    "this ref is only on 1 move line", rec_ref)
                continue
            total = 0.0
            accounts = {}
            partners = {}
            for line in lines_to_rec:
                total += line.credit
                total -= line.debit
                accounts[line.account_id] = True
                partners[line.partner_id.id or False] = True
            if not comp_cur.is_zero(total):
                logger.warning(
                    "Skip reconcile of ref '%s' because the lines with "
                    "this ref are not balanced (%s)", rec_ref, total)
                continue
            if len(accounts) > 1:
                logger.warning(
                    "Skip reconcile of ref '%s' because the lines with "
                    "this ref have different accounts (%s)",
                    rec_ref, ', '.join([acc.code for acc in accounts.keys()]))
                continue
            if not list(accounts)[0].reconcile:
                logger.warning(
                    "Skip reconcile of ref '%s' because the account '%s' "
                    "is not configured with 'Allow Reconciliation'",
                    rec_ref, list(accounts)[0].display_name)
                continue
            if len(partners) > 1:
                logger.warning(
                    "Skip reconcile of ref '%s' because the lines with "
                    "this ref have different partners (IDs %s)",
                    rec_ref, ', '.join(partners.keys()))
                continue
            lines_to_rec.reconcile()
        logger.info('Reconcile imported moves finished')
