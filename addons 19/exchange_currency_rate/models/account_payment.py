from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    is_exchange = fields.Boolean(string='Apply Manual Exchange', copy=True)
    rate = fields.Float(string='Exchange Rate', digits=(12, 6), default=1.0, copy=True)
    rate_display = fields.Char(string='Rate', compute='_compute_rate_display', store=False)

    @api.depends('rate', 'currency_id', 'company_id')
    def _compute_rate_display(self):
        for payment in self:
            company_currency = payment.company_id.currency_id if payment.company_id else False
            if payment.currency_id and company_currency and payment.currency_id != company_currency:
                payment.rate_display = '1 %s = %.4f %s' % (
                    payment.currency_id.name,
                    payment.rate or 0.0,
                    company_currency.name,
                )
            else:
                payment.rate_display = ''

    def _get_locked_currency_rate(self):
        self.ensure_one()
        return self.rate or 1.0

    def _manual_balance_from_amount_currency(self, amount_currency):
        self.ensure_one()
        return amount_currency * (self.rate or 1.0)

    def _find_manual_exchange_invoice(self):
        self.ensure_one()
        invoices = self.reconciled_invoice_ids if 'reconciled_invoice_ids' in self._fields else self.env['account.move']
        invoices = invoices.filtered(lambda m: m.rate and m.rate > 0 and m.currency_id == self.currency_id)
        if invoices:
            return invoices[:1]
        memo = getattr(self, 'memo', False) or getattr(self, 'ref', False)
        if memo:
            domain = [
                ('company_id', '=', self.company_id.id),
                ('currency_id', '=', self.currency_id.id),
                ('move_type', 'in', ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')),
                ('rate', '>', 0),
                '|',
                ('name', '=', memo),
                ('payment_reference', '=', memo),
            ]
            invoice = self.env['account.move'].search(domain, limit=1)
            if invoice:
                return invoice
        return self.env['account.move']

    def _sync_manual_exchange_from_invoice(self):
        for payment in self:
            invoice = payment._find_manual_exchange_invoice()
            if invoice and invoice.currency_id != invoice.company_currency_id:
                vals = {
                    'is_exchange': True,
                    'rate': invoice.rate,
                }
                payment.sudo().write(vals)
                payment._sync_manual_exchange_to_move(vals)

    def _sync_manual_exchange_to_move(self, vals=None):
        for payment in self:
            move = payment.move_id
            if not move:
                continue
            move.sudo().write({
                'is_exchange': vals['is_exchange'] if vals and 'is_exchange' in vals else payment.is_exchange,
                'rate': vals['rate'] if vals and 'rate' in vals else (payment.rate or 1.0),
            })

    def _manual_exchange_move_lines(self):
        self.ensure_one()
        move = self.move_id
        if not move or not self.currency_id or self.currency_id == self.company_id.currency_id:
            return self.env['account.move.line']
        return move.line_ids.filtered(lambda line: line.currency_id == self.currency_id and line.amount_currency)

    def _apply_manual_exchange_rate_on_move_lines(self):
        for payment in self:
            if not payment.rate or payment.rate <= 0:
                continue
            if not payment.currency_id or payment.currency_id == payment.company_id.currency_id:
                continue
            payment._sync_manual_exchange_to_move({
                'is_exchange': payment.is_exchange,
                'rate': payment.rate,
            })
            lines = payment._manual_exchange_move_lines()
            if not lines:
                continue
            for line in lines:
                balance = payment._manual_balance_from_amount_currency(line.amount_currency)
                line.with_context(
                    check_move_validity=False,
                    skip_account_move_synchronization=True,
                ).sudo().write({
                    'currency_rate': payment._get_locked_currency_rate(),
                    'balance': balance,
                    'debit': balance if balance > 0 else 0.0,
                    'credit': -balance if balance < 0 else 0.0,
                })

    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        for payment in payments:
            if payment.rate and payment.currency_id != payment.company_id.currency_id:
                payment._sync_manual_exchange_to_move()
                payment._apply_manual_exchange_rate_on_move_lines()
        return payments

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ('is_exchange', 'rate')):
            self._sync_manual_exchange_to_move(vals)
            self._apply_manual_exchange_rate_on_move_lines()
        return res

    def action_post(self):
        self._sync_manual_exchange_from_invoice()
        self._apply_manual_exchange_rate_on_move_lines()
        res = super().action_post()
        self._sync_manual_exchange_from_invoice()
        self._sync_manual_exchange_to_move()
        self._apply_manual_exchange_rate_on_move_lines()
        return res
