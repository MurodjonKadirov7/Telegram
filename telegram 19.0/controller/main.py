import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class TelegramWebhook(http.Controller):

    @http.route(
        '/telegram/webhook/<string:secret_token>',
        methods=['POST'],
        type='http',
        auth='public',
        csrf=False,
    )
    def webhook(self, secret_token, **kwargs):
        """
        Receive Telegram webhook updates.

        Best-practice: secret_token is set in the webhook URL itself.
        Telegram sends it as the last path segment when you call setWebhook
        with secret_token parameter.

        Current scope: only handle /start command to map username -> chat_id.
        """
        # Verify secret token
        expected_token = request.env['ir.config_parameter'].sudo().get_param(
            'telegram_send.webhook_secret'
        )
        if not expected_token or secret_token != expected_token:
            _logger.warning('Telegram webhook: invalid secret token')
            return request.make_response('Forbidden', status=403)

        try:
            data = json.loads(request.httprequest.data)
        except Exception:
            _logger.warning('Telegram webhook: invalid JSON body')
            return request.make_response('Bad Request', status=400)

        try:
            request.env['telegram.send.wizard'].sudo()._process_webhook_update(data)
        except Exception:
            _logger.exception('Telegram webhook: error processing update')

        return request.make_response('OK', status=200)
