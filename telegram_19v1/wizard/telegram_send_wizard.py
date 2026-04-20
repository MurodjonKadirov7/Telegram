import base64
import logging
import mimetypes
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

BULK_SEND_LIMIT = 20
TELEGRAM_API_URL = 'https://api.telegram.org/bot{token}/{method}'


class TelegramSendWizard(models.TransientModel):
    _name = 'telegram.send.wizard'
    _description = 'Send Telegram Message Wizard'

    # ----------------------------------------------------------------
    # Context-driven fields
    # ----------------------------------------------------------------
    res_model = fields.Char(string='Document Model', readonly=True)
    res_id = fields.Integer(string='Document ID', readonly=True)

    # ----------------------------------------------------------------
    # Wizard fields
    # ----------------------------------------------------------------
    partner_ids = fields.Many2many(
        comodel_name='res.partner',
        string='Recipients',
        domain=[('telegram_chat_id', '!=', False), ('telegram_chat_id', '!=', '')],
        required=True,
    )
    report_id = fields.Many2one(
        comodel_name='ir.actions.report',
        string='Report (PDF)',
    )
    message = fields.Text(string='Message')
    attachment_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='tg_wizard_attachment_rel',
        string='Attachments',
    )
    # Computed IDs used as domain filter for report_id in the view
    allowed_report_domain_ids = fields.Many2many(
        comodel_name='ir.actions.report',
        relation='tg_wizard_allowed_reports_rel',
        string='Allowed Reports (computed)',
        compute='_compute_allowed_report_domain_ids',
    )

    @api.depends('res_model')
    def _compute_allowed_report_domain_ids(self):
        for rec in self:
            if rec.res_model:
                rec.allowed_report_domain_ids = self.env['telegram.model.config']._get_allowed_reports(rec.res_model)
            else:
                rec.allowed_report_domain_ids = self.env['ir.actions.report']

    # ----------------------------------------------------------------
    # default_get: read active_model / active_id from context
    # ----------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        ctx = self.env.context
        model = ctx.get('active_model')
        rec_id = ctx.get('active_id')

        if model:
            result['res_model'] = model
        if rec_id:
            result['res_id'] = rec_id

        return result

    # ----------------------------------------------------------------
    # Compute allowed report domain (used in view via attrs)
    # ----------------------------------------------------------------
    @api.onchange('res_model')
    def _onchange_res_model(self):
        """Update report_id domain when model is known."""
        if self.res_model:
            allowed = self.env['telegram.model.config']._get_allowed_reports(self.res_model)
            return {'domain': {'report_id': [('id', 'in', allowed.ids)]}}
        return {'domain': {'report_id': []}}

    # ----------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------
    def _validate(self):
        self.ensure_one()
        if not self.partner_ids:
            raise ValidationError(_('Please select at least one recipient.'))
        if not self.message and not self.report_id and not self.attachment_ids:
            raise ValidationError(_('Please enter a message, select a report, or add an attachment.'))
        if len(self.partner_ids) > BULK_SEND_LIMIT:
            raise ValidationError(
                _('You can send to a maximum of %s recipients at a time.') % BULK_SEND_LIMIT
            )

    # ----------------------------------------------------------------
    # Main send action
    # ----------------------------------------------------------------
    def action_send(self):
        self.ensure_one()
        self._validate()
        self._check_user_access()

        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_('The selected document no longer exists.'))

        bot_token = self._get_bot_token()

        pdf_data = None
        if self.report_id:
            pdf_data = self._render_pdf(record)

        success_partners = []
        failed_partners = []

        for partner in self.partner_ids:
            chat_id = partner.telegram_chat_id
            errors = []

            # Send text
            if self.message:
                ok, err = self._send_message(bot_token, chat_id, self.message)
                if not ok:
                    errors.append(err)

            # Send PDF
            if self.report_id and pdf_data:
                ok, err = self._send_file(bot_token, chat_id, pdf_data, self.report_id.name + '.pdf', 'application/pdf')
                if not ok:
                    errors.append(err)

            # Send attachments
            for attachment in self.attachment_ids:
                file_data = base64.b64decode(attachment.datas)
                mimetype = attachment.mimetype or 'application/octet-stream'
                ok, err = self._send_file(bot_token, chat_id, file_data, attachment.name, mimetype)
                if not ok:
                    errors.append(err)

            if errors:
                failed_partners.append((partner, '; '.join(errors)))
                self._write_log(partner, status='error', error_message='; '.join(errors))
            else:
                success_partners.append(partner)
                self._write_log(partner, status='sent')

        # Write chatter log on the record
        self._post_chatter_message(record, success_partners, failed_partners)

        if failed_partners:
            raise UserError(
                _('Some messages could not be delivered. Please try again later.')
            )

        return {'type': 'ir.actions.act_window_close'}

    # ----------------------------------------------------------------
    # Helpers: Telegram API calls
    # ----------------------------------------------------------------
    def _get_bot_token(self):
        token = self.env['ir.config_parameter'].sudo().get_param('telegram_19v1.bot_token')
        if not token:
            raise UserError(
                _('Telegram bot token is not configured. Please go to Settings > Telegram.')
            )
        return token

    def _check_user_access(self):
        config = self.env['telegram.model.config'].search([
            ('model_name', '=', self.res_model),
            ('active', '=', True),
        ], limit=1)
        if not config:
            raise UserError(_('Telegram sending is not configured for this document type.'))
        if config.allowed_user_ids and self.env.user not in config.allowed_user_ids:
            raise UserError(_('You are not allowed to send Telegram messages from this document type.'))

    def _send_message(self, token, chat_id, text):
        """Send plain text message. Returns (success, error_message)."""
        url = TELEGRAM_API_URL.format(token=token, method='sendMessage')
        try:
            resp = requests.post(url, json={'chat_id': chat_id, 'text': text}, timeout=10)
            data = resp.json()
            if data.get('ok'):
                return True, None
            return False, data.get('description', 'Unknown error')
        except Exception as e:
            _logger.exception('Telegram sendMessage error for chat_id=%s', chat_id)
            return False, str(e)

    def _send_file(self, token, chat_id, file_bytes, filename, mimetype):
        """Send any file via Telegram. Returns (success, error_message)."""
        url = TELEGRAM_API_URL.format(token=token, method='sendDocument')
        try:
            resp = requests.post(
                url,
                data={'chat_id': chat_id},
                files={'document': (filename, file_bytes, mimetype)},
                timeout=30,
            )
            data = resp.json()
            if data.get('ok'):
                return True, None
            return False, data.get('description', 'Unknown error')
        except Exception as e:
            _logger.exception('Telegram sendDocument error for chat_id=%s', chat_id)
            return False, str(e)

    def _render_pdf(self, record):
        """Render the selected report to PDF bytes."""
        try:
            pdf_content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
                self.report_id,
                record.ids,
            )
            return pdf_content
        except Exception as e:
            _logger.exception('PDF render error: report=%s record=%s', self.report_id.name, record.id)
            raise UserError(_('Could not render the PDF report: %s') % str(e)) from e

    # ----------------------------------------------------------------
    # Logging
    # ----------------------------------------------------------------
    def _write_log(self, partner, status, error_message=None, telegram_response=None):
        self.env['telegram.message.log'].create({
            'partner_id': partner.id,
            'chat_id': partner.telegram_chat_id,
            'res_model': self.res_model,
            'res_id': self.res_id,
            'message_text': self.message or False,
            'report_id': self.report_id.id if self.report_id else False,
            'status': status,
            'error_message': error_message,
            'telegram_response': telegram_response,
        })

    # ----------------------------------------------------------------
    # Webhook: /start handler — maps username to chat_id
    # ----------------------------------------------------------------
    @api.model
    def _process_webhook_update(self, data):
        """
        Process an incoming Telegram update.
        Only /start command is handled: maps from.username -> partner.telegram_chat_id.
        """
        message = data.get('message', {})
        if not message:
            return

        text = message.get('text', '')
        from_data = message.get('from', {})
        chat_data = message.get('chat', {})

        username = from_data.get('username', '').lower()
        chat_id = str(chat_data.get('id', ''))

        if not username or not chat_id:
            return

        if text.strip().startswith('/start'):
            partner = self.env['res.partner'].sudo().search(
                [('telegram_username', '=ilike', username)],
                limit=1,
            )
            if partner:
                if partner.telegram_chat_id != chat_id:
                    partner.write({'telegram_chat_id': chat_id})
                    _logger.info(
                        'Telegram: chat_id %s mapped to partner %s (username: %s)',
                        chat_id, partner.id, username,
                    )
            else:
                _logger.info(
                    'Telegram /start: no partner found for username=%s', username
                )

    def _post_chatter_message(self, record, success_partners, failed_partners):
        """Write a short log message to the record chatter."""
        if not hasattr(record, 'message_post'):
            return

        lines = []
        if success_partners:
            names = ', '.join(p.name for p in success_partners)
            parts = []
            if self.message:
                parts.append(_('text'))
            if self.report_id:
                parts.append(_('PDF: %s') % self.report_id.name)
            if self.attachment_ids:
                att_names = ', '.join(self.attachment_ids.mapped('name'))
                parts.append(_('Files: %s') % att_names)
            lines.append(_('✅ Telegram sent to: %s (%s)') % (names, ', '.join(parts)))

        if failed_partners:
            for partner, err in failed_partners:
                lines.append(_('❌ Telegram failed for %s: %s') % (partner.name, err))

        if lines:
            record.message_post(
                body='<br/>'.join(lines),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        ctx = self.env.context
        model = ctx.get('active_model')
        rec_id = ctx.get('active_id')

        if model:
            result['res_model'] = model
        if rec_id:
            result['res_id'] = rec_id

        # Pre-fill with record's existing attachments
        if model and rec_id:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', model),
                ('res_id', '=', rec_id),
            ])
            if attachments:
                result['attachment_ids'] = [fields.Command.set(attachments.ids)]

        return result