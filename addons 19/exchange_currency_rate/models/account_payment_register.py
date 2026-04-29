from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    is_exchange = fields.Boolean(
        string='Apply Manual Exchange',
        default=True,
        help='Copied from the invoice when opening Register Payment.',
    )
    rate = fields.Float(
        string='Exchange Rate',
        digits=(12, 6),
        default=1.0,
        help='Copied from the invoice: 1 payment currency = X company currency.',
    )
    rate_display = fields.Char(string='Rate', compute='_compute_rate_display', store=False)

    @api.model
    def _get_context_moves(self):
        if self:
            moves = self.mapped('line_ids.move_id').filtered(lambda m: m.is_invoice(include_receipts=True))
            if moves:
                return moves
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        active_id = self.env.context.get('active_id')
        if not active_ids and active_id:
            active_ids = [active_id]
        if active_model == 'account.move' and active_ids:
            return self.env['account.move'].browse(active_ids).exists().filtered(
                lambda m: m.is_invoice(include_receipts=True)
            )
        if active_model == 'account.move.line' and active_ids:
            return self.env['account.move.line'].browse(active_ids).exists().mapped('move_id').filtered(
                lambda m: m.is_invoice(include_receipts=True)
            )
        return self.env['account.move']

    def _get_active_moves(self):
        return self._get_context_moves()

    @api.model
    def _get_manual_exchange_values_from_context_moves(self):
        moves = self._get_context_moves().filtered(
            lambda m: m.currency_id
            and m.company_currency_id
            and m.currency_id != m.company_currency_id
            and m.rate
            and m.rate > 0
        )
        if not moves:
            return {}
        first = moves[0]
        same_currency_and_rate = all(
            m.currency_id == first.currency_id
            and m.company_currency_id == first.company_currency_id
            and abs((m.rate or 0.0) - (first.rate or 0.0)) < 0.000001
            for m in moves
        )
        if not same_currency_and_rate:
            return {}
        return {
            'is_exchange': True,
            'rate': first.rate,
        }

    def _get_locked_currency_rate(self):
        self.ensure_one()
        return (1.0 / self.rate) if self.rate else 1.0

    def _get_manual_exchange_source_move(self):
        self.ensure_one()
        values = self.env['account.payment.register']._get_manual_exchange_values_from_context_moves()
        if not values:
            return False
        moves = self._get_context_moves().filtered(lambda m: m.rate)
        return moves[:1]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        values = self._get_manual_exchange_values_from_context_moves()
        if values:
            res.update(values)
        return res

    @api.depends('is_exchange', 'rate', 'currency_id', 'company_id')
    def _compute_rate_display(self):
        for wizard in self:
            company_currency = wizard.company_id.currency_id if wizard.company_id else False
            if wizard.currency_id and company_currency and wizard.currency_id != company_currency:
                wizard.rate_display = '1 %s = %.4f %s' % (
                    wizard.currency_id.name,
                    wizard.rate or 0.0,
                    company_currency.name,
                )
            else:
                wizard.rate_display = ''

    @api.onchange('journal_id', 'currency_id', 'payment_date', 'amount')
    def _onchange_keep_invoice_manual_rate(self):
        values = self.env['account.payment.register']._get_manual_exchange_values_from_context_moves()
        if values:
            for wizard in self:
                wizard.is_exchange = values['is_exchange']
                wizard.rate = values['rate']

    @api.onchange('is_exchange')
    def _onchange_is_exchange(self):
        values = self.env['account.payment.register']._get_manual_exchange_values_from_context_moves()
        if values:
            for wizard in self:
                wizard.is_exchange = values['is_exchange']
                wizard.rate = values['rate']

    @api.constrains('rate')
    def _check_manual_exchange_rate(self):
        for wizard in self:
            if wizard.rate is not False and wizard.rate <= 0:
                raise ValidationError('Manual exchange rate must be greater than zero.')

    def _inject_manual_rate_in_payment_vals(self, vals):
        self.ensure_one()
        values = self.env['account.payment.register']._get_manual_exchange_values_from_context_moves()
        rate = values.get('rate') or self.rate
        apply_manual = values.get('is_exchange', self.is_exchange)
        if rate and rate > 0:
            vals.update({
                'is_exchange': bool(apply_manual),
                'rate': rate,
            })
        return vals

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        return self._inject_manual_rate_in_payment_vals(vals)

    def _create_payment_vals_from_batch(self, batch_result):
        vals = super()._create_payment_vals_from_batch(batch_result)
        return self._inject_manual_rate_in_payment_vals(vals)

    def _apply_manual_rate_to_payment_moves(self, payments):
        for wizard in self:
            values = self.env['account.payment.register']._get_manual_exchange_values_from_context_moves()
            rate = values.get('rate') or wizard.rate
            apply_manual = values.get('is_exchange', wizard.is_exchange)
            if not rate or rate <= 0:
                continue
            for payment in payments:
                payment.sudo().write({
                    'is_exchange': bool(apply_manual),
                    'rate': rate,
                })
                if hasattr(payment, '_apply_manual_exchange_rate_on_move_lines'):
                    payment._apply_manual_exchange_rate_on_move_lines()
        return payments

    def _init_payments(self, to_process, edit_mode=False):
        payments = super()._init_payments(to_process, edit_mode=edit_mode)
        return self._apply_manual_rate_to_payment_moves(payments)

    def _create_payments(self):
        payments = super()._create_payments()
        return self._apply_manual_rate_to_payment_moves(payments)
