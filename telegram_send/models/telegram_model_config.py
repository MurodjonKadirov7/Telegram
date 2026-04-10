from odoo import api, fields, models


class TelegramModelConfig(models.Model):
    _name = 'telegram.model.config'
    _description = 'Telegram Model Configuration'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    model_id = fields.Many2one(
        comodel_name='ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
    )
    model_name = fields.Char(
        related='model_id.model',
        string='Model Name',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    allowed_report_ids = fields.Many2many(
        comodel_name='ir.actions.report',
        string='Allowed Reports',
        domain="[('model', '=', model_name)]",
        help='Reports that can be sent via Telegram for this model. Leave empty to allow all reports.',
    )
    allowed_user_ids = fields.Many2many(
        comodel_name='res.users',
        string='Allowed Users',
        help='Users who can send Telegram messages from this model. Leave empty to allow all users.',
    )

    _sql_constraints = [
        ('model_unique', 'unique(model_id)', 'A Telegram config already exists for this model.'),
    ]

    @api.depends('model_id')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.model_id.name if rec.model_id else ''

    def _can_send_telegram(self, model_name):
        """Check if current user can send Telegram from given model."""
        config = self.search([('model_name', '=', model_name), ('active', '=', True)], limit=1)
        if not config:
            return False
        if not config.allowed_user_ids:
            return True
        return self.env.user in config.allowed_user_ids

    def _get_allowed_reports(self, model_name):
        """Return allowed reports for the model."""
        config = self.search([('model_name', '=', model_name), ('active', '=', True)], limit=1)
        if not config:
            return self.env['ir.actions.report']
        if config.allowed_report_ids:
            return config.allowed_report_ids
        # If no reports configured, return all reports for that model
        return self.env['ir.actions.report'].search([('model', '=', model_name)])
