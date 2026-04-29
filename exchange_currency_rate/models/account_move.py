from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_exchange = fields.Boolean(
        string='Apply Manual Exchange',
        copy=True,
        help='Enable to force this move to use the rate below.',
    )
    rate = fields.Float(
        string='Exchange Rate',
        default=1.0,
        copy=True,
        digits=(12, 6),
        help='1 unit of document currency = X units of company currency.',
    )
    rate_display = fields.Char(
        string='Rate',
        compute='_compute_rate_display',
        store=False,
    )

    def _get_inverted_rate(self):
        self.ensure_one()
        if not self.currency_id or not self.company_currency_id or self.currency_id == self.company_currency_id:
            return 1.0
        odoo_rate = self.env['res.currency']._get_conversion_rate(
            from_currency=self.company_currency_id,
            to_currency=self.currency_id,
            company=self.company_id,
            date=self._get_invoice_currency_rate_date() or fields.Date.context_today(self),
        )
        return (1.0 / odoo_rate) if odoo_rate else 1.0

    def _get_locked_currency_rate(self):
        self.ensure_one()
        return (1.0 / self.rate) if self.rate else 1.0

    @api.depends('rate', 'currency_id', 'company_currency_id')
    def _compute_rate_display(self):
        for move in self:
            if move.currency_id and move.company_currency_id and move.currency_id != move.company_currency_id:
                move.rate_display = '1 %s = %.4f %s' % (
                    move.currency_id.name,
                    move.rate or 0.0,
                    move.company_currency_id.name,
                )
            else:
                move.rate_display = ''

    @api.onchange('is_exchange', 'currency_id', 'company_id', 'invoice_date')
    def _onchange_manual_exchange(self):
        for move in self:
            if move.currency_id == move.company_currency_id:
                move.is_exchange = False
                move.rate = 1.0
            elif move.is_exchange and (not move.rate or move.rate <= 0):
                move.rate = move._get_inverted_rate()
            elif move.is_exchange and move.rate == 1.0:
                move.rate = move._get_inverted_rate()

    @api.constrains('is_exchange', 'rate', 'currency_id', 'company_currency_id')
    def _check_manual_exchange_rate(self):
        for move in self:
            if move.is_exchange:
                if move.currency_id == move.company_currency_id:
                    raise ValidationError('Manual exchange rate can only be enabled when document currency differs from company currency.')
                if not move.rate or move.rate <= 0:
                    raise ValidationError('Manual exchange rate must be greater than zero.')

    @api.depends(
        'currency_id',
        'company_currency_id',
        'company_id',
        'invoice_date',
        'rate',
        'is_exchange',
    )
    def _compute_invoice_currency_rate(self):
        for move in self:
            if not move.is_invoice(include_receipts=True) or move.currency_id == move.company_currency_id:
                move.invoice_currency_rate = 1.0
            elif move.is_exchange and move.rate:
                move.invoice_currency_rate = move._get_locked_currency_rate()
            else:
                move.invoice_currency_rate = self.env['res.currency']._get_conversion_rate(
                    from_currency=move.company_currency_id,
                    to_currency=move.currency_id,
                    company=move.company_id,
                    date=move._get_invoice_currency_rate_date(),
                )

    def _post(self, soft=True):
        res = super()._post(soft=soft)
        for move in self:
            if move.rate and move.rate > 0 and move.currency_id != move.company_currency_id:
                lines = move.line_ids.filtered(lambda line: line.currency_id == move.currency_id and line.amount_currency)
                lines.sudo().write({'currency_rate': move._get_locked_currency_rate()})
        return res

    def js_assign_outstanding_line(self, line_id):
        self.ensure_one()
        if self.rate and self.rate > 0 and self.currency_id != self.company_currency_id:
            self.env['account.move.line'].browse(line_id).sudo().write({
                'currency_rate': self._get_locked_currency_rate(),
            })
        return super().js_assign_outstanding_line(line_id)

    def _reverse_moves(self, default_values_list=None, cancel=False):
        reversed_moves = super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)
        for original, reverse in zip(self, reversed_moves):
            if original.is_exchange and original.rate:
                reverse.write({
                    'is_exchange': original.is_exchange,
                    'rate': original.rate,
                })
        return reversed_moves
