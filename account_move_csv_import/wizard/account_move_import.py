# Copyright 2012-2025 Akretion France (https://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, Command
from odoo.exceptions import UserError
from odoo.tools.mimetypes import guess_mimetype
from datetime import datetime, date as datelib
from markupsafe import Markup
import csv
import re
from tempfile import NamedTemporaryFile
import base64
import logging

logger = logging.getLogger(__name__)
try:
    import openpyxl  # for XLSX
except ImportError:
    logger.debug('Cannot import openpyxl')
try:
    import xlrd  # for XLS
except ImportError:
    logger.debug('Cannot import xlrd')
try:
    from odsparsator import odsparsator
except ImportError:
    odsparsator = None
    logger.debug('Cannot import odsparsator')


CSV_QUOTING = {
    'minimal': csv.QUOTE_MINIMAL,
    'all': csv.QUOTE_ALL,
    'none': csv.QUOTE_NONE,
    }


class AccountMoveImport(models.TransientModel):
    _name = "account.move.import"
    _description = "Import account move from file"
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True, default=lambda self: self.env.company)
    file_to_import = fields.Binary(string='File to Import', required=True)
    filename = fields.Char()
    config_id = fields.Many2one(
        "account.move.import.config", required=True, check_company=True,
        string="Import Configuration",
        domain="[('company_id', 'in', (False, company_id))]",
        compute="_compute_config_id", store=True, readonly=False, precompute=True)
    post_move = fields.Boolean(
        string='Post and Reconcile',
        compute="_compute_default_values", store=True, readonly=False, precompute=True,
        help="If enabled, the journal entries will be posted and, if the Reconcile Ref "
        "is available in the import file, Odoo will reconcile the journal items.")
    force_move_ref = fields.Char(
        string='Force Reference',
        compute="_compute_default_values", store=True, readonly=False, precompute=True)
    force_move_line_name = fields.Char(
        string='Force Label',
        compute="_compute_default_values", store=True, readonly=False, precompute=True)
    force_move_date = fields.Date('Force Date')
    force_move_date_required = fields.Boolean(related="config_id.force_move_date_required")

    @api.depends('company_id')
    def _compute_config_id(self):
        for wiz in self:
            config_id = False
            if wiz.company_id:
                config = self.env['account.move.import.config'].search([
                    ('company_id', 'in', (False, wiz.company_id.id))], limit=1)
                if config:
                    config_id = config.id
            wiz.config_id = config_id

    @api.depends('config_id')
    def _compute_default_values(self):
        for wiz in self:
            if wiz.config_id:
                wiz.post_move = wiz.config_id.default_post_move
                wiz.force_move_ref = wiz.config_id.default_force_move_ref
                wiz.force_move_line_name = wiz.config_id.default_force_move_line_name

    # PIVOT FORMAT
    # [{
    #    'account': '411000',
    #    'analytic': 'ADM',  # analytic account code (100% distribution)
    # OR 'analytic': 'ADM:39.4,SUPP:60.6',  # analytic distribution
    #    'partner': 'R1242',  # Partner code
    #    'partner_name': 'Tiny Sprl',   # Partner name (used when config.create_partner = True)
    #    'name': 'label',  # optional, for account.move.line
    #    'credit': 12.42,
    #    'debit': 0,
    #    'ref': '9804',  # optional
    #    'journal': 'VT',  # journal code
    #    'journal_id': 4,  # when journal is forced
    #    'date': '2025-02-15',  # as datetime or as string in '%Y-%m-%d'
    #    'date_maturity': '2025-03-14',  # same format as 'date'
    #    'move_name': 'OD/2022/1242',  # optional, for 'name' of account.move
    #                                  # only used when keep_odoo_move_name = False
    #    'reconcile_ref': 'A1242',  # will be written in import_reconcile
    #                               # and be processed after move line creation
    #    'line': 2,  # Line number for error messages.
    #                # Must be the exact line number from the user point of view
    # },
    #  2nd line...
    #  3rd line...
    # ]

    def _file2pivot(self, fileobj, file_bytes):
        file_format = self.config_id.file_format
        method_name = f"_{file_format}2pivot"
        if not hasattr(self, method_name):
            raise UserError(
                self.env._(
                    "Method '%s' doesn't exist. This should never happen.", method_name
                ))
        method = getattr(self, method_name)
        pivot = method(fileobj, file_bytes)
        return pivot

    def run_import(self):
        self.ensure_one()
        if not self.file_to_import:
            raise UserError(self.env._("You must upload a file to import."))
        suffix = ''
        if self.filename:
            suffix = self.filename.split('.')[-1]
            suffix = f".{suffix}"
        with NamedTemporaryFile('wb+', prefix='odoo-move_import-', suffix=suffix) as fileobj:
            file_bytes = base64.b64decode(self.file_to_import)
            fileobj.write(file_bytes)
            fileobj.seek(0)  # We must start reading from the beginning !
            pivot = self._file2pivot(fileobj, file_bytes)
        logger.debug('pivot before update: %s', pivot)
        pivot = self._update_pivot(pivot)
        moves, created_account_codes = self._create_moves_from_pivot(pivot, post=self.post_move)
        if self.post_move:
            self._reconcile_move_lines(moves)
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_move_journal_line")
        # We need to remove from context 'search_default_posted': 1
        action['context'] = {'default_move_type': 'entry', 'view_no_maturity': True}
        if len(moves) == 1:
            action.update({
                'view_mode': 'form,list',
                'res_id': moves[0].id,
                'view_id': False,
                'views': [(False, "form")],
                })
        else:
            action.update({
                'domain': [('id', 'in', moves.ids)],
                })
        if created_account_codes:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'sticky': True,
                    'title': self.env._("%s account(s) created", len(created_account_codes)),
                    'message': self.env._(
                        "The following accounts have been automatically created: %s.",
                        ", ".join([str(code) for code in created_account_codes])),
                    "next": action,
                    },
                }
        return action

    def _update_pivot(self, pivot):
        force_move_date = self.force_move_date
        force_move_ref = self.force_move_ref
        force_move_line_name = self.force_move_line_name
        config = self.config_id.with_company(self.company_id.id)
        force_journal_id = config.force_journal_id.id or False
        non_str_cols = ['date', 'date_maturity', 'debit', 'credit', 'line']
        for l in pivot:
            for key, value in l.items():
                if value:
                    if isinstance(value, str):
                        l[key] = value.strip() or False
                else:
                    l[key] = False
                if value and key not in non_str_cols:
                    if isinstance(value, int):
                        l[key] = str(value)
                    elif isinstance(value, float):
                        l[key] = str(int(value))
            if force_move_date:
                l['date'] = force_move_date
            if force_move_line_name:
                l['name'] = force_move_line_name
            if force_move_ref:
                l['ref'] = force_move_ref
            if force_journal_id:
                l['journal_id'] = force_journal_id
        # remove lines without account (useful to auto-remove a total line at the end)
        pivot_no_lines_without_account = [l for l in pivot if l.get('account')]
        return pivot_no_lines_without_account

    def _update_date_using_date_format(self, pivot):
        date_format = self.config_id.date_format
        field2label = {
            'date': self.env._('Date'),
            'date_maturity': self.env._('Due Date'),
            }
        for vals in pivot:
            for key, field_label in field2label.items():
                if vals.get(key) and isinstance(vals[key], str):
                    try:
                        vals[key] = datetime.strptime(vals[key], date_format)
                    except Exception:
                        raise UserError(self.env._(
                            "Parsing error on line %(line)s for field '%(field_label)s': "
                            "'%(date)s' does not match date format '%(date_format)s'.",
                            line=vals['line'],
                            field_label=field_label,
                            date=vals[key],
                            date_format=date_format))

    def _fec_txt2pivot(self, fileobj, file_bytes):
        fieldnames = [
            'journal',        # JournalCode
            False,            # JournalLib
            'move_name',      # EcritureNum
            'date',           # EcritureDate
            'account',        # CompteNum
            'account_name',   # CompteLib
            'partner_ref',    # CompAuxNum
            'partner_name',   # CompAuxLib
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
        res = []
        try:
            first_line = fileobj.readline().decode()
            dialect = csv.Sniffer().sniff(first_line, delimiters="|\t")
        except Exception:
            raise UserError(self.env._(
                "Could not detect the field delimited. Please check that "
                "file '%(filename)s' it is a text FEC file.",
                filename=self.filename))
        encoding = self.config_id.encoding
        logger.info(
            'FEC import auto-detected delimiter: %s',
            dialect.delimiter == '\t' and 'tab' or dialect.delimiter)
        fileobj.seek(0)
        with open(fileobj.name, newline='', encoding=encoding) as f:
            reader = csv.DictReader(
                f,
                fieldnames=fieldnames,
                delimiter=dialect.delimiter)
            line = 0
            for l in reader:
                line += 1
                # Skip header line
                if line == 1:
                    continue
                l['credit'] = l['credit'] or '0'
                l['debit'] = l['debit'] or '0'
                vals = {
                    'journal': l['journal'],
                    'move_name': l['move_name'],
                    'account': l['account'],
                    'account_name': l['account_name'],
                    'partner': l['partner_ref'],
                    'partner_name': l['partner_name'],
                    'credit': float(l['credit'].replace(',', '.')),
                    'debit': float(l['debit'].replace(',', '.')),
                    'date': datetime.strptime(l['date'], '%Y%m%d'),
                    'name': l['name'],
                    'ref': l['ref'],
                    'reconcile_ref': l['reconcile_ref'],
                    'line': line,
                }
                res.append(vals)
        return res

    def _csv2pivot(self, fileobj, file_bytes):
        # I use utf-8-sig instead of utf-8 to transparently handle BOM
        # https://en.wikipedia.org/wiki/Byte_order_mark
        config = self.config_id
        pfield2position = config._get_pfield2position()
        encoding = config.encoding == 'utf-8' and 'utf-8-sig' or config.encoding
        delimiter = config.delimiter == "tab" and "\t" or config.delimiter
        quoting = CSV_QUOTING[config.quoting]
        start_line = config.start_line
        decimal_separator = config.decimal_separator
        res = []
        with open(fileobj.name, newline='', encoding=encoding) as f:
            reader = csv.reader(
                f,
                delimiter=delimiter,
                quotechar='"',
                quoting=quoting)
            line = 0
            for row in reader:
                line += 1
                if line < start_line:
                    continue
                if not row:  # skip empty lines
                    continue
                vals = {'line': line}
                for pfield, position in pfield2position.items():
                    if position is not None:
                        length = position + 1
                        if len(row) >= length:
                            vals[pfield] = row[position] or False
                        else:
                            logger.info(
                                'Cannot get %s from row n°%s at position %s because len(row)=%s.',
                                pfield, line, position, len(row))
                            continue
                        if pfield in ('debit', 'credit'):
                            if vals[pfield] and isinstance(vals[pfield], str):
                                # keep only digits and decimal separator ; remove everything else
                                vals[pfield] = ''.join(re.findall(fr'[\d{decimal_separator}]', vals[pfield]))
                                if vals[pfield]:
                                    if decimal_separator != '.':
                                        vals[pfield] = vals[pfield].replace(decimal_separator, '.')
                                    try:
                                        vals[pfield] = float(vals[pfield])
                                    except Exception as err:
                                        raise UserError(self.env._(
                                            "Float parsing error on line %(line)s: '%(value)s' "
                                            "could not be converted to a float. Error: %(err)s",
                                            value=vals[pfield],
                                            line=line, err=err))
                            if not vals[pfield]:
                                vals[pfield] = 0
                res.append(vals)
        self._update_date_using_date_format(res)
        return res

    def _xlsx_xls_ods2pivot(self, fileobj, file_bytes):
        mime_res = guess_mimetype(file_bytes)
        if mime_res == 'application/vnd.oasis.opendocument.spreadsheet':  # ODS
            pivot = self._ods2pivot(fileobj)
        elif mime_res == 'application/vnd.ms-excel':  # XLS
            pivot = self._xls2pivot(fileobj)
        elif mime_res == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':  # XLSX
            pivot = self._xlsx2pivot(fileobj)
        else:
            raise UserError(self.env._(
                "The file '%s' is not an XLSX, XLS nor ODS file.", self.filename))
        self._update_date_using_date_format(pivot)
        return pivot

    def _xlsx2pivot(self, fileobj):
        wb = openpyxl.load_workbook(fileobj.name, read_only=True, data_only=True)
        config = self.config_id
        sheet = wb.worksheets[config.sheet_number - 1]
        pfield2position = config._get_pfield2position()
        start_line = config.start_line
        res = []
        line = 0
        for row in sheet.rows:
            line += 1
            if line < start_line:
                continue
            if not [item for item in row if item.value]:
                # skip empty line
                continue
            vals = {'line': line}
            for pfield, position in pfield2position.items():
                if position is not None:
                    length = position + 1
                    if len(row) >= length:
                        vals[pfield] = row[position].value or False
                    else:
                        logger.info(
                            'Cannot get %s from row n°%s at position %s because len(row)=%s.',
                            pfield, line, position, len(row))
                        continue
            res.append(vals)
        return res

    def _xls2pivot(self, fileobj):
        wb = xlrd.open_workbook(fileobj.name)
        config = self.config_id
        sh = wb.sheet_by_index(config.sheet_number - 1)
        pfield2position = config._get_pfield2position()
        start_line = config.start_line
        res = []
        line = 0
        for row_int in range(sh.nrows):
            line += 1
            if line < start_line:
                continue
            row = sh.row(row_int)
            if not [item for item in row if item.value]:
                # skip empty line
                continue
            vals = {'line': line}
            for pfield, position in pfield2position.items():
                if position is not None:
                    length = position + 1
                    if len(row) >= length:
                        vals[pfield] = row[position].value or False
                    else:
                        logger.info(
                            'Cannot get %s from row n°%s at position %s because len(row)=%s.',
                            pfield, line, position, len(row))
                        continue
                    if pfield in ("date", "date_maturity") and isinstance(vals[pfield], (float, int)) and vals[pfield]:
                        vals[pfield] = datetime(*xlrd.xldate_as_tuple(vals[pfield], wb.datemode))
            res.append(vals)
        return res

    def _ods2pivot(self, fileobj):
        if odsparsator is None:
            raise UserError(self.env._(
                "To import ods files, you must install the odsparsator python library. "
                "See https://pypi.org/project/odsparsator"))
        config = self.config_id
        pfield2position = config._get_pfield2position()
        start_line = config.start_line

        odsdict = odsparsator.ods_to_python(fileobj.name)
        line = 0
        res = []
        for rowdict in odsdict['body'][config.sheet_number - 1]['table']:
            line += 1
            # print('Line %s row=%s' % (line, row))
            if line < start_line:
                continue
            row = rowdict['row']
            if not row:  # skip empty line
                continue
            vals = {'line': line}
            for pfield, position in pfield2position.items():
                if position is not None:
                    length = position + 1
                    if len(row) >= length:
                        if isinstance(row[position], dict):
                            vals[pfield] = row[position].get('value')
                        else:
                            vals[pfield] = row[position]
                    else:
                        logger.info(
                            'Cannot get %s from row n°%s at position %s because len(row)=%s.',
                            pfield, line, position, len(row))
                        continue
                    if pfield in ("date", "date_maturity"):
                        # if it's a date cell in ODS, it will be given as string %Y-%m-%d
                        try:
                            vals[pfield] = datetime.strptime(vals[pfield], "%Y-%m-%d")
                        except Exception:
                            pass
                        # if it's a string cell in ODS, it will be reformatted in the method
                        # _update_date_using_date_format()
            res.append(vals)
        return res

    def _quadra2pivot(self, file_bytes):
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

    def _prepare_partner_speeddict(self, company_id):
        speeddict = {}
        partner_sr = self.env['res.partner'].with_context(active_test=False).search_read(
            [
                '|',
                ('company_id', '=', company_id),
                ('company_id', '=', False),
                ('ref', '!=', False),
                ('parent_id', '=', False),
            ],
            ['ref'])
        for l in partner_sr:
            speeddict[l['ref'].upper()] = l['id']
        return speeddict

    def _prepare_speeddict(self, company_id):
        speeddict = {
            "partner": self._prepare_partner_speeddict(company_id),
            "journal": {},
            "account": {},
            "analytic": {},
            "account_id2rec": {},
            "account_id2code": {},
            }
        acc_sr = self.env['account.account'].with_company(company_id).search_read([
            ('company_ids', 'in', company_id),
            ('deprecated', '=', False)], ['code', 'reconcile'])
        for l in acc_sr:
            speeddict['account'][l['code'].upper()] = l['id']
            speeddict['account_id2rec'][l['id']] = l['reconcile']
            speeddict['account_id2code'][l['id']] = l['code']
        aacc_sr = self.env['account.analytic.account'].search_read(
            [('company_id', 'in', (company_id, False)), ('code', '!=', False)],
            ['code'])
        for l in aacc_sr:
            speeddict['analytic'][l['code'].upper()] = l['id']
        journal_sr = self.env['account.journal'].search_read([
            ('company_id', '=', company_id)], ['code'])
        for l in journal_sr:
            speeddict['journal'][l['code'].upper()] = l['id']
        return speeddict

    def _prepare_new_partner(self, pivot_entry, speeddict):
        vals = {
            'is_company': True,
            'name': pivot_entry.get('partner_name') or pivot_entry['partner'],
            'active': False,
            'ref': pivot_entry['partner'],
            'comment': 'Partner automatically created by journal entry import.',
            }
        return vals

    def _prepare_new_account(self, account_code, account_name, company_id):
        """Prepare values for creating a new account.
        Fields 'account_type' and 'reconcile' are computed fields and
        the native code works fine to compute them
        """
        vals = {
            'code': account_code,
            'name': account_name or account_code,
            'company_ids': [Command.set([company_id])],
            }
        return vals

    def _create_moves_from_pivot(self, pivot, post=False):
        logger.debug('Final pivot: %s', pivot)
        amo = self.env['account.move']
        rpo = self.env['res.partner']
        aao = self.env['account.account']
        company_id = self.company_id.id
        config = self.config_id
        create_partner = config.create_partner
        create_account = config.create_account
        speeddict = self._prepare_speeddict(company_id)
        key2label = {
            'journal': self.env._('journal codes'),
            'account': self.env._('account codes'),
            'partner': self.env._('partner reference'),
            'analytic': self.env._('analytic codes'),
            }
        errors = {'other': []}
        created_account_codes = []
        for key in key2label.keys():
            errors[key] = {}

        if config.skip_first_journal:
            pivot_skip_first_journal = []
            first_journal_code = False
            for l in pivot:
                if not first_journal_code:
                    first_journal_code = l.get('journal')
                if first_journal_code == l.get('journal'):
                    logger.info('Skip line %s in journal %s because option skip_first_journal is enabled', l['line'], l.get('journal'))
                else:
                    pivot_skip_first_journal.append(l)
            pivot = pivot_skip_first_journal
        if config.groupby_move_name:
            pivot_groupby_move_name = sorted(pivot, key=lambda to_sort: to_sort['move_name'])
            pivot = pivot_groupby_move_name
        # MATCHES + CHECKS
        for l in pivot:
            assert l.get('line') and isinstance(l.get('line'), int), \
                'missing line number'
            if l['account'] in speeddict['account']:
                l['account_id'] = speeddict['account'][l['account']]
            if not l.get('account_id'):
                # Match when import = 61100000 and Odoo has 611000
                acc_code_tmp = l['account']
                while acc_code_tmp and acc_code_tmp[-1] == '0':
                    acc_code_tmp = acc_code_tmp[:-1]
                    if acc_code_tmp and acc_code_tmp in speeddict['account']:
                        l['account_id'] = speeddict['account'][acc_code_tmp]
                        break
            if not l.get('account_id'):
                # Match when import = 611000 and Odoo has 611000XX
                for code, account_id in speeddict['account'].items():
                    if code.startswith(l['account']):
                        logger.warning(
                            "Approximate match: import account %s has been matched "
                            "with Odoo account %s" % (l['account'], code))
                        l['account_id'] = account_id
                        break
            if not l.get('account_id'):
                if create_account and l.get('account'):
                    account_name = l.get("account_name") or l.get("name")
                    # Create the account automatically
                    account = aao.create(self._prepare_new_account(
                        l['account'], account_name, company_id))
                    account = account.with_company(company_id)
                    account.message_post(body=Markup(self.env._(
                        "Account auto-created by the wizard "
                        "<strong>Import Journal Entries</strong>.")))
                    logger.info('Account %s created', account.display_name)
                    speeddict['account'][l['account'].upper()] = account.id
                    speeddict['account_id2rec'][account.id] = account.reconcile
                    speeddict['account_id2code'][account.id] = account.code
                    l['account_id'] = account.id
                    created_account_codes.append(account.code)
                else:
                    errors['account'].setdefault(l['account'], []).append(l['line'])
            else:
                reconcile = speeddict['account_id2rec'][l['account_id']]
                if not reconcile and l.get('reconcile_ref'):
                    logger.info(
                        'Remove reconcile_ref %s on line %s because account %s '
                        'is not reconciliable',
                        l['reconcile_ref'], l['line'], speeddict['account_id2code'][l['account_id']])
                    l['reconcile_ref'] = False
            if l.get('partner'):
                if l['partner'] not in speeddict['partner'] and create_partner:
                    partner = rpo.create(self._prepare_new_partner(l, speeddict))
                    logger.info('Partner %s reference %s created', partner.display_name, l['partner'])
                    speeddict['partner'][l['partner']] = partner.id
                if l['partner'] in speeddict['partner']:
                    l['partner_id'] = speeddict['partner'][l['partner']]
                else:
                    errors['partner'].setdefault(l['partner'], []).append(l['line'])
            if l.get('analytic'):
                l['analytic_distribution'] = {}
                for ana_entry in l['analytic'].split('|'):
                    ana_entry = ana_entry.strip()
                    if ana_entry:
                        ana_entry_split = ana_entry.split(':')
                        if len(ana_entry_split) == 1:
                            ana_account_code = ana_entry_split[0].strip()
                            ana_pct = 100
                        elif len(ana_entry_split) > 1:
                            ana_account_code = ':'.join(ana_entry_split[:-1]).strip()
                            ana_pct_str = ana_entry_split[-1]
                            ana_pct_str_ready = ana_pct_str.replace(',', '.')
                            try:
                                ana_pct = float(ana_pct_str_ready)
                            except Exception:
                                errors['other'].append("Line %d: wrong analytic percentage: '%s' is not a number." % (l['line'], ana_pct_str))
                                ana_pct = 1
                            if ana_pct < 0 or ana_pct > 100:
                                errors['other'].append("Line %d: wrong analytic percentage: '%s' is not between 0 and 100." % (l['line'], ana_pct_str))
                        if ana_account_code in speeddict['analytic']:
                            l['analytic_distribution'][speeddict['analytic'][ana_account_code]] = ana_pct
                        else:
                            errors['analytic'].setdefault(ana_account_code, []).append(l['line'])

            if not l.get('journal_id'):
                if l['journal'] in speeddict['journal']:
                    l['journal_id'] = speeddict['journal'][l['journal']]
                else:
                    errors['journal'].setdefault(l['journal'], []).append(l['line'])
            if not l.get('date'):
                errors['other'].append(self.env._(
                    'Line %d: missing date.', l['line']))
            else:
                if not isinstance(l.get('date'), datelib):
                    try:
                        l['date'] = datetime.strptime(l['date'], '%Y-%m-%d')
                    except Exception:
                        errors['other'].append(self.env._(
                            "Line %(line)s: field 'Date' has an invalid date '%(date)s'",
                            line=l['line'], date=l['date']))
            if l.get('date_maturity'):
                if not isinstance(l.get('date_maturity'), datelib):
                    try:
                        l['date_maturity'] = datetime.strptime(l['date_maturity'], '%Y-%m-%d')
                    except Exception:
                        errors['other'].append(self.env._(
                            "Line %(line)s: field 'Due Date' has an invalid date '%(date)s'",
                            line=l['line'], date=l['date_maturity']))
            if not isinstance(l.get('credit'), (float, int)):
                errors['other'].append(self.env._(
                    'Line %(line)s: bad value for credit (%(credit)s).',
                    line=l['line'], credit=l['credit']))
            if not isinstance(l.get('debit'), (float, int)):
                errors['other'].append(self.env._(
                    'Line %(line)s: bad value for debit (%(debit)s).',
                    line=l['line'], debit=l['debit']))
            # test that they don't have both a value
        # LIST OF ERRORS
        msg = ''
        for key, label in key2label.items():
            if errors[key]:
                errors_key_sorted = sorted(errors[key].items(), key=lambda x: x[0])
                msg += self.env._("List of %(label)s that don't exist in Odoo:\n%(err)s\n\n",
                    label=label,
                    err='\n'.join([
                        '- %s : line(s) %s' % (code, ', '.join([str(i) for i in lines]))
                        for (code, lines) in errors_key_sorted]))
        if errors['other']:
            msg += self.env._('List of misc errors:\n%s',
                '\n'.join(['- %s' % e for e in errors['other']]))
        if msg:
            raise UserError(msg)
        # EXTRACT MOVES
        skip_null_lines = config.skip_null_lines
        split_move_method = config.split_move_method
        date_by_move_line = config.date_by_move_line
        moves = []
        cur_journal_id = False
        cur_move_name = False
        cur_date = False
        cur_balance = 0.0
        comp_cur = self.company_id.currency_id
        seq = self.env['ir.sequence'].next_by_code('account.move.import')
        cur_move = {}
        for l in pivot:
            if (
                    skip_null_lines and
                    comp_cur.is_zero(l['credit']) and
                    comp_cur.is_zero(l['debit'])):
                logger.info('Skip line %d which has debit=credit=0', l['line'])
                continue
            move_name = l.get('move_name')
            if split_move_method == 'move_name':
                if not move_name:
                    errors['other'].append(self.env._(
                        'Line %s: missing journal entry number.', l['line']))
                same_move = [cur_move_name == move_name]
            elif split_move_method == 'balanced':
                same_move = [
                    cur_journal_id == l['journal_id'],
                    not comp_cur.is_zero(cur_balance)]
                if not date_by_move_line:
                    same_move.append(cur_date == l['date'])
            else:
                raise UserError(self.env._("Wrong Move Split Method."))
            if all(same_move):  # append to current move
                cur_move['line_ids'].append(Command.create(self._prepare_move_line(l, seq, speeddict)))
            else:  # new move
                if cur_move:
                    if len(cur_move['line_ids']) <= 1:
                        raise UserError(self.env._(
                            "Journal entry on line %(line)s only has 1 line.\n\n"
                            "Debug data: %(debug)s", line=l['line'], debug=cur_move['line_ids']))
                    moves.append(cur_move)
                if not comp_cur.is_zero(cur_balance):
                    raise UserError(self.env._(
                        "Journal entry on line %(line)s is not balanced.",
                        line=l['line'] -1))
                cur_move = self._prepare_move(l)
                cur_move['line_ids'] = [Command.create(self._prepare_move_line(l, seq, speeddict))]
                cur_date = l['date']
                cur_move_name = move_name
                cur_journal_id = l['journal_id']
                cur_balance = 0.0
            cur_balance += l['credit'] - l['debit']
        if cur_move:
            moves.append(cur_move)
        if not comp_cur.is_zero(cur_balance):
            raise UserError(self.env._(
                "The journal entry that ends on the last line is not "
                "balanced (balance is %s).", cur_balance))
        logger.info('Starting to create %d account moves', len(moves))
        start = datetime.now()
        rmoves = amo.create(moves)
        end = datetime.now()
        seconds = (end-start).seconds
        logger.info('%d account moves created in %d seconds', len(rmoves), seconds)
        if post:
            logger.info('Starting to post %d account moves', len(rmoves))
            rmoves._post(soft=False)
            logger.info('%d account moves posted', len(rmoves))
        return rmoves, created_account_codes

    def _prepare_move(self, pivot_line):
        vals = {
            'journal_id': pivot_line['journal_id'],
            'ref': pivot_line.get('ref'),
            'date': pivot_line['date'],
            }
        if pivot_line.get('move_name') and not self.config_id.keep_odoo_move_name:
            vals['name'] = pivot_line['move_name']
        return vals

    def _prepare_move_line(self, pivot_line, sequence, speeddict):
        # some software like Quadra consider that a reconcile mark is specific to an account
        # so I concat the account ID and the reconcile_ref
        import_reconcile = False
        if pivot_line.get('reconcile_ref'):
            account_code = speeddict['account_id2code'][pivot_line['account_id']]
            import_reconcile = f"{account_code}-{pivot_line['reconcile_ref']}"
        vals = {
            'credit': pivot_line['credit'],
            'debit': pivot_line['debit'],
            'name': pivot_line.get('name'),
            'partner_id': pivot_line.get('partner_id'),
            'account_id': pivot_line['account_id'],
            'analytic_distribution': pivot_line.get('analytic_distribution'),
            'date_maturity': pivot_line.get('date_maturity'),
            'import_reconcile': import_reconcile,
            'import_external_id': f"{sequence}-{pivot_line.get('line')}",
            }
        return vals

    def _reconcile_move_lines(self, moves):
        comp_cur = self.company_id.currency_id
        logger.info('Start to reconcile imported moves')
        ml_domain = [
            ('import_reconcile', '!=', False),
            ('parent_state', '=', 'posted'),
            ('account_id.reconcile', '=', True),
            ('reconciled', '=', False),
            ]
        if self.config_id.reconcile_policy == 'current':
            ml_domain.append(('move_id', 'in', moves.ids))
        lines = self.env['account.move.line'].search(ml_domain)
        logger.info('%d account move lines with import_reconcile to analyse for reconciliation', len(lines))
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
            accounts = set()
            partners = set()
            for line in lines_to_rec:
                total += line.credit
                total -= line.debit
                accounts.add(line.account_id)
                partners.add(line.partner_id.id or False)
            if not comp_cur.is_zero(total):
                logger.warning(
                    "Skip reconcile of ref '%s' because the lines with "
                    "this ref are not balanced (%s)", rec_ref, total)
                continue
            if len(accounts) > 1:
                logger.warning(
                    "Skip reconcile of ref '%s' because the lines with "
                    "this ref have different accounts (%s)",
                    rec_ref, ', '.join([acc.code for acc in accounts]))
                continue
            lines_to_rec.reconcile()
        logger.info('Reconcile imported moves finished')
