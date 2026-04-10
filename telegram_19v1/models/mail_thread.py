from odoo import models
from odoo.addons.mail.tools.discuss import Store


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _thread_to_store(self, store: Store, fields, *, request_list=None):
        super()._thread_to_store(store, fields, request_list=request_list)
        if request_list:
            can_send_telegram = self.env['telegram.model.config']._can_send_telegram(self._name)
            store.add(self, {'canSendTelegram': can_send_telegram}, as_thread=True)
