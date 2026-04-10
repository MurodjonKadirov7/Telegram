from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    telegram_username = fields.Char(
        string='Telegram Username',
        help='Telegram username (without @)',
    )
    telegram_chat_id = fields.Char(
        string='Telegram Chat ID',
        help='Telegram chat ID. Auto-filled when the contact sends /start to the bot.',
    )
