from odoo import models


class PurchaseOrder(models.Model):
	_inherit = 'purchase.order'

	def update_product_description(self):
		for record in self:
			record.order_line._update_product_description()


class PurchaseOrderLine(models.Model):
	_inherit = 'purchase.order.line'

	def _update_product_description(self):
		for line in self:
			if not line.product_id:
				return
			params = {'order_id': line.order_id}
			seller = line.product_id._select_seller(
				partner_id=line.partner_id,
				quantity=line.product_qty,
				date=line.order_id.date_order and line.order_id.date_order.date(),
				uom_id=line.product_uom,
				params=params)

			if seller and seller.product_name or seller.product_code:
				line.name = "[{}] {}".format(seller.product_code, seller.product_name)
			if not line.name:
				product_lang = line.product_id.with_context(
					lang=line.partner_id.lang,
					partner_id=line.partner_id.id,
				)
				line.name = product_lang.display_name
				if product_lang.description_purchase:
					line.name += '\n' + product_lang.description_purchase
		return True
