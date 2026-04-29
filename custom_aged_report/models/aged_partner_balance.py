from odoo import models, fields, api, _
from odoo.osv import expression


class AgedPartnerBalanceCustomHandler(models.AbstractModel):
    _inherit = 'account.aged.partner.balance.report.handler'

    def open_customer_statement(self, options, params):
        report = self.env['account.report'].browse(options['report_id'])
        record_model, _record_id = report._get_model_info_from_id(params.get('line_id'))
        if record_model != 'res.partner':
            return False
        return super().open_customer_statement(options, params)


    def _get_custom_display_config(self):
        config = super()._get_custom_display_config()
        components = dict(config.get('components', {}))
        components['AccountReportFilters'] = 'custom_aged_report.AgedPartnerBalanceFilters'
        config['components'] = components
        return config

    def _custom_line_postprocessor(self, report, options, lines):
        lines = super()._custom_line_postprocessor(report, options, lines)
        report_currency_id = self._get_currency_id(options) or self.env.company.currency_id.id
        monetary_indexes = [
            idx for idx, column in enumerate(options.get('columns', []))
            if column.get('figure_type') == 'monetary'
        ]

        for line in lines:
            columns = line.get('columns', [])
            for idx in monetary_indexes:
                if idx >= len(columns):
                    continue
                column_dict = columns[idx]
                if not isinstance(column_dict, dict):
                    continue
                format_params = dict(column_dict.get('format_params') or {})
                format_params['currency_id'] = report_currency_id
                column_dict['format_params'] = format_params
                # Let account_report formatter rebuild display with the target currency symbol.
                column_dict.pop('name', None)
        return lines

    def _custom_options_initializer(self, report, options, previous_options=None):
        previous_options = previous_options or {}
        super()._custom_options_initializer(report, options, previous_options=previous_options)

        options['salesperson_ids'] = previous_options.get('salesperson_ids', [])
        options['account_ids'] = previous_options.get('account_ids', [])
        prev_currency_id = previous_options.get('report_currency_filter_id')
        if isinstance(prev_currency_id, dict):
            prev_currency_id = prev_currency_id.get('id')
        try:
            prev_currency_id = int(prev_currency_id) if prev_currency_id else False
        except (TypeError, ValueError):
            prev_currency_id = False
        options['report_currency_filter_id'] = prev_currency_id
        options['show_payment_lines'] = previous_options.get('show_payment_lines', True)
        payment_lines_mode = previous_options.get('payment_lines_mode')
        if payment_lines_mode not in ('all', 'matched', 'unmatched', 'none'):
            payment_lines_mode = 'all' if options['show_payment_lines'] else 'none'
        options['payment_lines_mode'] = payment_lines_mode
        options['payment_lines_mode_choices'] = [
            {'id': 'all', 'name': _('All Payments')},
            {'id': 'unmatched', 'name': _('Only Unmatched')},
            {'id': 'matched', 'name': _('Only Matched')},
            {'id': 'none', 'name': _('Hide Payments')},
        ]
        options['groupby_mode'] = previous_options.get('groupby_mode', 'partner')
        options['groupby_mode_choices'] = [
            {'id': 'partner', 'name': _('Group by Partner')},
            {'id': 'salesperson', 'name': _('Group by Salesperson')},
            {'id': 'account', 'name': _('Group by Account')},
        ]
        self._apply_groupby_mode(report, options['groupby_mode'])
        salespeople = self.env['res.users'].search([
            ('share', '=', False),
            ('active', '=', True),
        ], order='name asc')
        options['salesperson_choices'] = [
            {'id': sp.id, 'name': sp.name}
            for sp in salespeople
        ]
        currencies = self.env['res.currency'].search([], order='name asc')
        options['currency_choices'] = [
            {'id': False, 'name': _('All Currencies')},
            *({'id': currency.id, 'name': currency.name} for currency in currencies),
        ]

        options['column_count'] = self._get_column_count(previous_options)
        options['column_count_choices'] = [
            {'id': 1, 'name': _('1 Period')},
            {'id': 2, 'name': _('2 Periods')},
            {'id': 3, 'name': _('3 Periods')},
            {'id': 4, 'name': _('4 Periods')},
            {'id': 5, 'name': _('5 Periods')},
            {'id': 6, 'name': _('6 Periods')},
            {'id': 8, 'name': _('8 Periods')},
            {'id': 10, 'name': _('10 Periods')},
            {'id': 12, 'name': _('12 Periods')},
            {'id': 15, 'name': _('15 Periods')},
        ]

        self._sort_period_columns(options)
        self._move_invoice_and_account_before_periods(options)
        self._apply_column_count_filter(options)
        self._apply_reporting_currency_on_columns(options)

    def _apply_groupby_mode(self, report, groupby_mode):
        mode_to_groupby = {
            'partner': 'partner_id,id',
            'salesperson': 'salesperson_group,partner_id,id',
            'account': 'account_group,partner_id,id',
        }
        target_groupby = mode_to_groupby.get(groupby_mode, 'partner_id,id')
        for xmlid in ('account_reports.aged_receivable_line', 'account_reports.aged_payable_line'):
            line = self.env.ref(xmlid, raise_if_not_found=False)
            if line and line.user_groupby != target_groupby:
                line.user_groupby = target_groupby

    def _get_custom_groupby_map(self):
        return {
            'salesperson_group': {
                'model': 'res.users',
                'domain_builder': lambda value: [('id', '=', 0)] if not value else ['|', ('move_id.salesperson_id', '=', int(value)), ('move_id.invoice_user_id', '=', int(value))],
            },
            'account_group': {
                'model': 'account.account',
                'domain_builder': lambda value: [('id', '=', 0)] if not value else [('account_id', '=', int(value))],
            },
        }

    def _get_salesperson_ids(self, options):
        raw = options.get('salesperson_ids', [])
        result = []
        for item in raw:
            if isinstance(item, dict):
                uid = item.get('id')
                if uid:
                    result.append(int(uid))
            elif isinstance(item, (int, float)):
                result.append(int(item))
        return result

    def _get_account_ids(self, options):
        raw = options.get('account_ids', [])
        result = []
        for item in raw:
            if isinstance(item, dict):
                acc_id = item.get('id')
                if acc_id:
                    result.append(int(acc_id))
            elif isinstance(item, (int, float)):
                result.append(int(item))
        return result

    def _get_currency_id(self, options):
        currency_id = options.get('report_currency_filter_id')
        if isinstance(currency_id, dict):
            currency_id = currency_id.get('id')
        try:
            return int(currency_id) if currency_id else False
        except (TypeError, ValueError):
            return False

    def _get_currency_domain(self, currency_id):
        if not currency_id:
            return []
        company_currency_id = self.env.company.currency_id.id
        if currency_id == company_currency_id:
            return ['|', ('currency_id', '=', False), ('currency_id', '=', company_currency_id)]
        return [('currency_id', '=', currency_id)]

    def _get_reporting_currency(self, options):
        currency_id = self._get_currency_id(options)
        if currency_id:
            return self.env['res.currency'].browse(currency_id)
        return self.env.company.currency_id

    def _convert_from_company_currency(self, amount, target_currency, date_to):
        company_currency = self.env.company.currency_id
        if not target_currency or target_currency == company_currency:
            return amount
        return company_currency._convert(
            amount,
            target_currency,
            self.env.company,
            date_to,
        )

    def _get_aml_amount_in_reporting_currency(self, aml, report_currency, date_to):
        company_currency = self.env.company.currency_id
        if report_currency == company_currency:
            return aml.balance
        if aml.currency_id and aml.currency_id == report_currency:
            return aml.amount_currency
        return self._convert_from_company_currency(aml.balance, report_currency, date_to)

    def _get_partial_amount_in_reporting_currency(self, part, counterpart_aml, report_currency, date_to):
        company_currency = self.env.company.currency_id
        if report_currency != company_currency and counterpart_aml.currency_id and counterpart_aml.currency_id == report_currency:
            if counterpart_aml.id == part.debit_move_id.id:
                return abs(part.debit_amount_currency)
            return abs(part.credit_amount_currency)
        return self._convert_from_company_currency(part.amount, report_currency, date_to)

    def _show_payment_lines(self, options):
        return bool(options.get('show_payment_lines', True))

    def _get_payment_lines_mode(self, options):
        mode = options.get('payment_lines_mode')
        if mode in ('all', 'matched', 'unmatched', 'none'):
            return mode
        return 'all' if self._show_payment_lines(options) else 'none'

    def _get_period_index(self, aml_date, date_to, interval, nb_periods):
        if not aml_date:
            return nb_periods - 1
        delta = (date_to - aml_date).days
        if delta < 0:
            return 0
        period_idx = (delta // interval) + 1
        return min(period_idx, nb_periods - 1)

    def _make_row(self, nb_periods, invoice_date, due_date, amount_currency,
                  currency_id, currency, account_name, partner_id, aml_id,
                  payment_id, period_idx, amount, has_sublines=True, salesperson_name=None):
        row = {f'period{i}': 0.0 for i in range(nb_periods)}
        row['invoice_date'] = invoice_date
        row['due_date'] = due_date
        row['amount_currency'] = amount_currency
        row['currency_id'] = currency_id
        row['currency'] = currency
        row['account_name'] = account_name
        row['salesperson_name'] = salesperson_name
        row['partner_id'] = partner_id
        row['aml_id'] = aml_id
        row['payment_id'] = payment_id
        row['aml_count'] = 1
        row['has_sublines'] = has_sublines
        row[f'period{period_idx}'] = amount
        row['total'] = amount
        return row

    def _get_invoice_move_types(self, internal_type):
        if internal_type == 'asset_receivable':
            return ['out_invoice', 'out_refund', 'out_receipt']
        return ['in_invoice', 'in_refund', 'in_receipt']

    def _get_invoice_domain(self, internal_type, date_to, salesperson_ids, account_ids=None, currency_id=False):
        domain = [
            ('date', '<=', fields.Date.to_string(date_to)),
            ('parent_state', '=', 'posted'),
        ]
        if account_ids:
            # Generic-account mode: keep regular journal lines here, and let payment lines
            # be handled by the dedicated unreconciled-payment query to avoid duplicates.
            domain += [
                ('account_id', 'in', account_ids),
                ('payment_id', '=', False),
            ]
        else:
            domain += [
                ('account_id.account_type', '=', internal_type),
                ('move_id.move_type', 'in', self._get_invoice_move_types(internal_type)),
            ]
        if salesperson_ids:
            domain += ['|', ('move_id.salesperson_id', 'in', salesperson_ids), ('move_id.invoice_user_id', 'in', salesperson_ids)]
        domain += self._get_currency_domain(currency_id)
        return domain

    def _get_move_salesperson(self, move):
        return move.salesperson_id or move.invoice_user_id

    def _get_unreconciled_payment_domain(self, internal_type, date_to, partner_ids=None, salesperson_ids=None, account_ids=None, currency_id=False):
        domain = [
            ('date', '<=', fields.Date.to_string(date_to)),
            ('parent_state', '=', 'posted'),
            ('payment_id', '!=', False),
            ('reconciled', '=', False),
        ]
        if partner_ids is not None:
            domain += [('partner_id', 'in', partner_ids)]
        if account_ids:
            domain += [('account_id', 'in', account_ids)]
        else:
            domain += [('account_id.account_type', '=', internal_type)]
        if salesperson_ids:
            domain += ['|', ('move_id.salesperson_id', 'in', salesperson_ids), ('move_id.invoice_user_id', 'in', salesperson_ids)]
        domain += self._get_currency_domain(currency_id)
        return domain

    def _get_row_grouping_key(self, current_groupby, aml_id, partner_id, salesperson_id=None, account_id=None):
        if current_groupby == 'id':
            return aml_id
        if current_groupby == 'partner_id':
            return partner_id
        if current_groupby == 'salesperson_group':
            return salesperson_id
        if current_groupby == 'account_group':
            return account_id
        return None

    def _aged_partner_report_custom_engine_common(self, options, internal_type, current_groupby, next_groupby, offset=0, limit=None):
        aging_date_field = 'invoice_date' if options.get('aging_based_on') == 'base_on_invoice_date' else 'date_maturity'
        date_to = fields.Date.from_string(options['date']['date_to'])
        interval = options.get('aging_interval', 30)
        salesperson_ids = self._get_salesperson_ids(options)
        account_ids = self._get_account_ids(options)
        currency_id = self._get_currency_id(options)
        report_currency = self._get_reporting_currency(options)
        selected_count = self._get_column_count(options)
        payment_lines_mode = self._get_payment_lines_mode(options)
        include_matched_payments = payment_lines_mode in ('all', 'matched')
        include_unmatched_payments = payment_lines_mode in ('all', 'unmatched')
        max_period_index = max(
            (choice.get('id', 0) for choice in options.get('column_count_choices', [])),
            default=selected_count,
        )
        nb_periods = max_period_index + 1
        forced_domain = options.get('forced_domain', [])
        invoice_domain = self._get_invoice_domain(internal_type, date_to, salesperson_ids, account_ids=account_ids, currency_id=currency_id)
        if forced_domain:
            invoice_domain = expression.AND([invoice_domain, forced_domain])
        invoice_lines = self.env['account.move.line'].search(
            invoice_domain
        )
        payment_period_domain = [
            ('date', '<=', fields.Date.to_string(date_to)),
            ('parent_state', '=', 'posted'),
            ('payment_id', '!=', False),
        ]
        if account_ids:
            payment_period_domain += [('account_id', 'in', account_ids)]
        else:
            payment_period_domain += [('account_id.account_type', '=', internal_type)]
        if salesperson_ids:
            payment_period_domain += ['|', ('move_id.salesperson_id', 'in', salesperson_ids), ('move_id.invoice_user_id', 'in', salesperson_ids)]
        payment_period_domain += self._get_currency_domain(currency_id)
        if forced_domain:
            payment_period_domain = expression.AND([payment_period_domain, forced_domain])
        multiplicator = 1 if internal_type == 'asset_receivable' else -1
        rows = []
        processed_payment_aml_ids = set()

        for aml in invoice_lines:
            salesperson = self._get_move_salesperson(aml.move_id)
            invoice_bucket_date = getattr(aml, aging_date_field) or aml.date_maturity or aml.invoice_date or aml.date
            inv_period_idx = self._get_period_index(invoice_bucket_date, date_to, interval, nb_periods)
            inv_period_idx = min(inv_period_idx, selected_count)
            inv_balance = multiplicator * self._get_aml_amount_in_reporting_currency(aml, report_currency, date_to)

            if abs(inv_balance) < 0.001:
                continue

            parts = aml.matched_credit_ids if internal_type == 'asset_receivable' else aml.matched_debit_ids

            matched_payments = []
            total_matched_same_period = 0.0

            for part in parts:
                if not part.max_date or part.max_date > date_to or not part.amount:
                    continue

                counterpart_aml = part.credit_move_id if internal_type == 'asset_receivable' else part.debit_move_id
                if not counterpart_aml:
                    continue

                pay_period_idx = self._get_period_index(part.max_date, date_to, interval, nb_periods)
                pay_period_idx = min(pay_period_idx, selected_count)

                matched_payments.append({
                    'aml_id': counterpart_aml.id,
                    'payment_id': counterpart_aml.payment_id.id if counterpart_aml.payment_id else None,
                    'account_id': counterpart_aml.account_id.id,
                    'account_name': counterpart_aml.account_id.code,
                    'currency_id': report_currency.id,
                    'currency': report_currency.display_name,
                    'date': part.max_date,
                    'period_idx': pay_period_idx,
                    'amount': self._get_partial_amount_in_reporting_currency(part, counterpart_aml, report_currency, date_to),
                })

                if pay_period_idx == inv_period_idx:
                    total_matched_same_period += part.amount

            total_matched = sum(p['amount'] for p in matched_payments)
            only_same_period = all(p['period_idx'] == inv_period_idx for p in matched_payments)

            if abs(total_matched - inv_balance) < 0.001 and only_same_period:
                continue

            net_invoice = inv_balance - total_matched_same_period
            if abs(net_invoice) >= 0.001:
                rows.append((
                    self._get_row_grouping_key(
                        current_groupby, aml.id, aml.partner_id.id,
                        salesperson_id=salesperson.id if salesperson else None,
                        account_id=aml.account_id.id,
                    ),
                    self._make_row(
                        nb_periods=nb_periods,
                        invoice_date=aml.invoice_date or aml.date,
                        due_date=aml.date_maturity or aml.date,
                        amount_currency=net_invoice,
                        currency_id=report_currency.id,
                        currency=report_currency.display_name,
                        account_name=aml.account_id.code,
                        partner_id=aml.partner_id.id,
                        aml_id=aml.id,
                        payment_id=None,
                        period_idx=inv_period_idx,
                        amount=net_invoice,
                        has_sublines=True,
                        salesperson_name=salesperson.name if salesperson else None,
                    )
                ))

            for pay in matched_payments:
                processed_payment_aml_ids.add(pay['aml_id'])
                if not include_matched_payments:
                    continue
                if pay['period_idx'] == inv_period_idx:
                    continue
                pay_amount = -pay['amount']
                rows.append((
                    self._get_row_grouping_key(
                        current_groupby, pay['aml_id'], aml.partner_id.id,
                        salesperson_id=salesperson.id if salesperson else None,
                        account_id=pay['account_id'],
                    ),
                    self._make_row(
                        nb_periods=nb_periods,
                        invoice_date=pay['date'],
                        due_date=pay['date'],
                        amount_currency=pay_amount,
                        currency_id=report_currency.id,
                        currency=report_currency.display_name,
                        account_name=pay['account_name'],
                        partner_id=aml.partner_id.id,
                        aml_id=pay['aml_id'],
                        payment_id=pay['payment_id'],
                        period_idx=pay['period_idx'],
                        amount=pay_amount,
                        has_sublines=False,
                        salesperson_name=salesperson.name if salesperson else None,
                    )
                ))

        partner_ids_from_invoices = invoice_lines.mapped('partner_id').ids
        has_payment_scope = bool(partner_ids_from_invoices) or bool(account_ids)
        if include_unmatched_payments and has_payment_scope:
            payment_domain = self._get_unreconciled_payment_domain(
                internal_type,
                date_to,
                partner_ids=partner_ids_from_invoices if partner_ids_from_invoices else None,
                salesperson_ids=salesperson_ids,
                account_ids=account_ids,
                currency_id=currency_id,
            )
            if forced_domain:
                payment_domain = expression.AND([payment_domain, forced_domain])
            for aml in self.env['account.move.line'].search(
                payment_domain
            ):
                if aml.id in processed_payment_aml_ids:
                    continue
                salesperson = self._get_move_salesperson(aml.move_id)
                pay_period_idx = self._get_period_index(aml.date, date_to, interval, nb_periods)
                pay_period_idx = min(pay_period_idx, selected_count)
                pay_balance = multiplicator * self._get_aml_amount_in_reporting_currency(aml, report_currency, date_to)
                if abs(pay_balance) < 0.001:
                    continue
                rows.append((
                    self._get_row_grouping_key(
                        current_groupby, aml.id, aml.partner_id.id,
                        salesperson_id=salesperson.id if salesperson else None,
                        account_id=aml.account_id.id,
                    ),
                    self._make_row(
                        nb_periods=nb_periods,
                        invoice_date=aml.date,
                        due_date=aml.date,
                        amount_currency=pay_balance,
                        currency_id=report_currency.id,
                        currency=report_currency.display_name,
                        account_name=aml.account_id.code,
                        partner_id=aml.partner_id.id,
                        aml_id=aml.id,
                        payment_id=aml.payment_id.id,
                        period_idx=pay_period_idx,
                        amount=pay_balance,
                        has_sublines=False,
                        salesperson_name=salesperson.name if salesperson else None,
                    )
                ))

        rows = self._deduplicate_rows(rows, nb_periods)
        return self._build_result(rows, current_groupby, nb_periods)

    def _deduplicate_rows(self, rows, nb_periods):
        seen = set()
        unique_rows = []
        for grouping_key, row in rows:
            period_values = tuple(round(row.get(f'period{i}', 0.0), 6) for i in range(nb_periods))
            signature = (
                grouping_key,
                row.get('partner_id'),
                row.get('aml_id'),
                row.get('payment_id'),
                row.get('invoice_date'),
                row.get('due_date'),
                row.get('salesperson_name'),
                row.get('account_name'),
                period_values,
            )
            if signature in seen:
                continue
            seen.add(signature)
            unique_rows.append((grouping_key, row))
        return unique_rows

    def _build_result(self, rows, current_groupby, nb_periods):
        if not current_groupby:
            rslt = {f'period{i}': 0.0 for i in range(nb_periods)}
            for _, row in rows:
                for i in range(nb_periods):
                    rslt[f'period{i}'] += row[f'period{i}']
            rslt.update({
                'invoice_date': None, 'due_date': None,
                'amount_currency': None, 'currency_id': None,
                'currency': None, 'account_name': None, 'salesperson_name': None,
                'total': sum(rslt[f'period{i}'] for i in range(nb_periods)),
                'has_sublines': False,
            })
            return rslt

        all_res_per_key = {}
        for grouping_key, row in rows:
            all_res_per_key.setdefault(grouping_key, []).append(row)

        rslt = []
        for grouping_key, row_list in all_res_per_key.items():
            merged = {f'period{i}': 0.0 for i in range(nb_periods)}
            for row in row_list:
                for i in range(nb_periods):
                    merged[f'period{i}'] += row[f'period{i}']
            if current_groupby == 'id':
                r = row_list[0]
                merged.update({
                    'invoice_date': r['invoice_date'],
                    'due_date': r['due_date'],
                    'amount_currency': r['amount_currency'],
                    'currency_id': r['currency_id'],
                    'currency': r['currency'],
                    'account_name': r['account_name'],
                    'salesperson_name': r.get('salesperson_name'),
                    'total': None,
                    'has_sublines': r['has_sublines'],
                    'partner_id': r['partner_id'],
                })
            else:
                merged.update({
                    'invoice_date': None, 'due_date': None,
                    'amount_currency': None, 'currency_id': None,
                    'currency': None, 'account_name': None, 'salesperson_name': None,
                    'total': sum(merged[f'period{i}'] for i in range(nb_periods)),
                    'has_sublines': False,
                })
            rslt.append((grouping_key, merged))
        return rslt

    def _get_column_count(self, options):
        try:
            return int(options.get('column_count', 15))
        except (TypeError, ValueError):
            return 15

    def _sort_period_columns(self, options):
        period_columns = [col for col in options['columns'] if col.get('expression_label', '').startswith('period')]
        if not period_columns:
            return
        sorted_periods = sorted(period_columns, key=lambda col: int(col['expression_label'].replace('period', '')))
        first_period_index = min(i for i, col in enumerate(options['columns']) if col.get('expression_label', '').startswith('period'))
        non_period_before = options['columns'][:first_period_index]
        non_period_after = [col for col in options['columns'][first_period_index:] if not col.get('expression_label', '').startswith('period')]
        options['columns'] = non_period_before + sorted_periods + non_period_after

    def _move_invoice_and_account_before_periods(self, options):
        columns = options.get('columns', [])
        if not columns:
            return
        salesperson_col = invoice_col = account_col = at_date_col = None
        period_cols = []
        other_cols = []
        for col in columns:
            label = col.get('expression_label', '')
            name = (col.get('name') or '').strip()
            if label == 'salesperson_name' or name in ('Sales Person', 'Salesperson'):
                salesperson_col = col
            elif label == 'invoice_date' or name == 'Invoice Date':
                invoice_col = col
            elif label == 'account_name' or name == 'Account':
                account_col = col
            elif label == 'period0':
                at_date_col = col
            elif label.startswith('period'):
                period_cols.append(col)
            else:
                other_cols.append(col)
        new_columns = []
        if salesperson_col:
            new_columns.append(salesperson_col)
        if invoice_col:
            new_columns.append(invoice_col)
        if account_col:
            new_columns.append(account_col)
        if at_date_col:
            new_columns.append(at_date_col)
        for col in period_cols:
            if col.get('expression_label') != 'period0':
                new_columns.append(col)
        new_columns.extend(other_cols)
        options['columns'] = new_columns

    def _apply_column_count_filter(self, options):
        interval = options.get('aging_interval', 30)
        selected_count = self._get_column_count(options)
        period_columns = [col for col in options['columns'] if col.get('expression_label', '').startswith('period')]
        if not period_columns:
            return
        filtered_columns = []
        for column in options['columns']:
            expression_label = column.get('expression_label', '')
            if not expression_label.startswith('period'):
                filtered_columns.append(column)
                continue
            period_number = int(expression_label.replace('period', ''))
            if period_number > selected_count:
                continue
            column['name'] = self._get_period_name(interval, period_number, selected_count)
            filtered_columns.append(column)
        options['columns'] = filtered_columns

    def _get_period_name(self, interval, period_number, selected_count):
        if period_number == 0:
            return _('At Date')
        if period_number == selected_count:
            return _('Older')
        start_day = interval * (period_number - 1) + 1
        end_day = interval * period_number
        return f'{start_day}-{end_day}'

    def _apply_reporting_currency_on_columns(self, options):
        report_currency_id = self._get_currency_id(options) or self.env.company.currency_id.id
        for column in options.get('columns', []):
            if column.get('figure_type') != 'monetary':
                continue
            format_params = dict(column.get('format_params') or {})
            format_params['currency_id'] = report_currency_id
            column['format_params'] = format_params


class AccountMove(models.Model):
    _inherit = 'account.move'

    salesperson_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        copy=False,
        index=True,
        help='Salesperson copied to payment journal entries for reporting and filtering.',
    )


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    salesperson_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        copy=False,
        index=True,
    )

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if payment.move_id and payment.salesperson_id:
                payment.move_id.salesperson_id = payment.salesperson_id.id
        return res


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    salesperson_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        compute='_compute_salesperson_id',
        readonly=False,
        store=False,
    )

    @api.depends('line_ids')
    def _compute_salesperson_id(self):
        for wizard in self:
            moves = wizard.line_ids.mapped('move_id')
            invoices = moves.filtered(lambda m: m.move_type in (
                'out_invoice', 'out_refund', 'out_receipt',
                'in_invoice', 'in_refund', 'in_receipt'
            ))
            salespersons = invoices.mapped('salesperson_id').filtered(lambda u: u)
            if not salespersons:
                salespersons = invoices.mapped('invoice_user_id').filtered(lambda u: u)
            wizard.salesperson_id = salespersons[0] if len(salespersons) == 1 else False

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.salesperson_id:
            vals['salesperson_id'] = self.salesperson_id.id
        return vals


class AgedReceivableGroupbyHandler(models.AbstractModel):
    _inherit = 'account.aged.receivable.report.handler'

    def _custom_unfold_all_batch_data_generator(self, report, options, lines_to_expand_by_function):
        line = self.env.ref('account_reports.aged_receivable_line', raise_if_not_found=False)
        if line and line._get_groupby(options).replace(' ', '') != 'partner_id,id':
            return {}
        return super()._custom_unfold_all_batch_data_generator(report, options, lines_to_expand_by_function)


class AgedPayableGroupbyHandler(models.AbstractModel):
    _inherit = 'account.aged.payable.report.handler'

    def _custom_unfold_all_batch_data_generator(self, report, options, lines_to_expand_by_function):
        line = self.env.ref('account_reports.aged_payable_line', raise_if_not_found=False)
        if line and line._get_groupby(options).replace(' ', '') != 'partner_id,id':
            return {}
        return super()._custom_unfold_all_batch_data_generator(report, options, lines_to_expand_by_function)