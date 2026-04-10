from odoo import fields, models


class TelegramMessageLog(models.Model):
    _name = 'telegram.message.log'
    _description = 'Telegram Message Log'
    _order = 'sent_at desc'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Recipient',
        index=True,
    )
    chat_id = fields.Char(string='Telegram Chat ID')
    res_model = fields.Char(string='Document Model')
    res_id = fields.Integer(string='Document ID')
    message_text = fields.Text(string='Message Text')
    report_id = fields.Many2one(
        comodel_name='ir.actions.report',
        string='Report',
    )
    status = fields.Selection(
        selection=[
            ('sent', 'Sent'),
            ('error', 'Error'),
        ],
        string='Status',
        default='sent',
    )
    telegram_response = fields.Text(string='Telegram Response')
    error_message = fields.Text(string='Error Message')
    sent_at = fields.Datetime(
        string='Sent At',
        default=fields.Datetime.now,
        readonly=True,
    )
    sent_by = fields.Many2one(
        comodel_name='res.users',
        string='Sent By',
        default=lambda self: self.env.user,
        readonly=True,
    )
