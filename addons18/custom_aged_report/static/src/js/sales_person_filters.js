/** @odoo-module **/

import { AccountReport } from "@account_reports/components/account_report/account_report";
import { AgedPartnerBalanceFilters as BaseAgedPartnerBalanceFilters } from "@account_reports/components/aged_partner_balance/filters";

export class AgedPartnerBalanceFilters extends BaseAgedPartnerBalanceFilters {
    static template = "custom_aged_report.AgedPartnerBalanceFilters";

    get groupbyModeChoices() {
        return this.controller.options?.groupby_mode_choices || [];
    }

    get selectedGroupbyModeLabel() {
        const selectedMode = this.controller.options?.groupby_mode;
        const selectedChoice = this.groupbyModeChoices.find((choice) => choice.id === selectedMode);
        return selectedChoice?.name || "Group By";
    }

    async setGroupbyMode(mode) {
        await this.filterClicked({ optionKey: "groupby_mode", optionValue: mode, reload: true });
    }

    get columnCountChoices() {
        return this.controller.options?.column_count_choices || [];
    }

    get selectedColumnCountLabel() {
        const selectedCount = this.controller.options?.column_count;
        const selectedChoice = this.columnCountChoices.find((choice) => choice.id === selectedCount);
        return selectedChoice?.name || "Periods";
    }

    async setColumnCount(count) {
        await this.filterClicked({ optionKey: "column_count", optionValue: count, reload: true });
    }

    get currencyChoices() {
        return this.controller.options?.currency_choices || [];
    }

    async setCurrency(currencyId) {
        await this.filterClicked({ optionKey: "report_currency_filter_id", optionValue: currencyId || false, reload: true });
    }

    get paymentLineModeChoices() {
        return this.controller.options?.payment_lines_mode_choices || [];
    }

    get paymentLineMode() {
        const mode = this.controller.options?.payment_lines_mode;
        if (mode) {
            return mode;
        }
        return this.controller.options?.show_payment_lines === false ? "none" : "all";
    }

    async setPaymentLineMode(mode) {
        await this.filterClicked({ optionKey: "payment_lines_mode", optionValue: mode, reload: true });
    }
}

AccountReport.registerCustomComponent(AgedPartnerBalanceFilters);