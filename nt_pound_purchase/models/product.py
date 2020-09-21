# -*- coding: utf-8 -*-

from odoo import models, fields, api


class Product(models.Model):
	_inherit = 'product.product'

	@api.model
	def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
		if not self.env.context.get('force_search_by_code_barcode', False):
			return super(Product, self)._name_search(name, args=args, operator=operator, limit=limit,
													 name_get_uid=name_get_uid)
		product_ids = self._search([('default_code', '=', name)], limit=limit, access_rights_uid=name_get_uid)
		if not product_ids:
			product_ids = self._search([('barcode', '=', name)], limit=limit, access_rights_uid=name_get_uid)
			if not product_ids:
				product_ids = self.env['product.ean']._search([('name', '=', name)], limit=limit, access_rights_uid=name_get_uid)
		return self.browse(product_ids).name_get()
