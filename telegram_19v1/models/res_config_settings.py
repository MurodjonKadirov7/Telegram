from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    telegram_bot_token = fields.Char(
        string='Telegram Bot Token',
        config_parameter='telegram_19v1.bot_token',
    )
    telegram_webhook_secret = fields.Char(
        string='Webhook Secret Token',
        config_parameter='telegram_19v1.webhook_secret',
    )
