from datetime import timedelta

from pytz import UTC, AmbiguousTimeError, NonExistentTimeError, UnknownTimeZoneError, timezone

from odoo import fields, models


WEEKEND_POLICY_DAYS = {
    'none': frozenset(),
    'sunday': frozenset({6}),
    'saturday': frozenset({5}),
    'weekend': frozenset({5, 6}),
}


class StockRule(models.Model):
    _inherit = 'stock.rule'

    weekend_policy = fields.Selection(
        selection=[
            ('none', 'No Weekend Exclusion'),
            ('sunday', 'Sunday Off'),
            ('saturday', 'Saturday Off'),
            ('weekend', 'Saturday and Sunday Off'),
        ],
        string='Weekend Policy',
        required=True,
        default='none',
        help='Weekend days excluded when applying this rule lead time.',
    )

    def _get_lead_time_timezone(self):
        self.ensure_one()
        company = self.company_id or self.warehouse_id.company_id or self.env.company
        timezone_name = company.resource_calendar_id.tz or self.env.user.tz or 'UTC'
        try:
            return timezone(timezone_name)
        except UnknownTimeZoneError:
            return UTC

    def _shift_lead_time_date(self, date_value, days, direction):
        self.ensure_one()
        date_datetime = fields.Datetime.to_datetime(date_value)
        if not date_datetime or not days:
            return date_datetime

        non_working_weekdays = WEEKEND_POLICY_DAYS[self.weekend_policy or 'none']
        if not non_working_weekdays:
            return date_datetime + timedelta(days=days * direction)

        local_timezone = self._get_lead_time_timezone()
        local_datetime = UTC.localize(date_datetime).astimezone(local_timezone).replace(tzinfo=None)
        signed_days = days * direction
        remaining_days = abs(signed_days)
        step = 1 if signed_days > 0 else -1
        while remaining_days:
            local_datetime += timedelta(days=step)
            if local_datetime.weekday() not in non_working_weekdays:
                remaining_days -= 1
        try:
            localized_datetime = local_timezone.localize(local_datetime, is_dst=None)
        except AmbiguousTimeError:
            localized_datetime = local_timezone.localize(local_datetime, is_dst=False)
        except NonExistentTimeError:
            localized_datetime = local_timezone.localize(
                local_datetime + timedelta(hours=1), is_dst=True,
            )
        return localized_datetime.astimezone(UTC).replace(tzinfo=None)

    def _get_push_new_date(self, move):
        self.ensure_one()
        return fields.Datetime.to_string(
            self._shift_lead_time_date(move.date, self.delay, direction=1)
        )

    def _get_stock_move_values(
        self, product_id, product_qty, product_uom, location_dest_id,
        name, origin, company_id, values,
    ):
        move_values = super()._get_stock_move_values(
            product_id, product_qty, product_uom, location_dest_id,
            name, origin, company_id, values,
        )
        move_values['date'] = fields.Datetime.to_string(
            self._shift_lead_time_date(values['date_planned'], self.delay, direction=-1)
        )
        if values.get('date_deadline'):
            move_values['date_deadline'] = fields.Datetime.to_string(
                self._shift_lead_time_date(values['date_deadline'], self.delay, direction=-1)
            )
        return move_values
