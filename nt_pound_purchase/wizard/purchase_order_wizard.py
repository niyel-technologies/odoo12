from json import dumps
from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.addons import decimal_precision as dp


class PurchaseOrderWizard(models.TransientModel):
	_name = 'purchase.order.wizard'
	_description = 'Purchase Order Wizard'

	@api.depends('order_line.price_total')
	def _amount_all(self):
		for order in self:
			amount_untaxed = amount_tax = 0.0
			for line in order.order_line:
				amount_untaxed += line.price_subtotal
				amount_tax += line.price_tax
			order.update({
				'amount_untaxed': order.currency_id.round(amount_untaxed),
				'amount_tax': order.currency_id.round(amount_tax),
				'amount_total': amount_untaxed + amount_tax,
			})

	order_id = fields.Many2one('purchase.order', domain=[('state', 'in', ['draft', 'sent'])], string="Purchase Order",
							   required=True)
	currency_id = fields.Many2one('res.currency', 'Currency', required=True, related='order_id.currency_id')
	order_line = fields.One2many(comodel_name="purchase.order.line.wizard", inverse_name="order_id", string="Lines")
	company_id = fields.Many2one('res.company', related='order_id.company_id', string='Company', readonly=True)
	amount_untaxed = fields.Monetary(string='Untaxed Amount', readonly=True, compute='_amount_all')
	amount_tax = fields.Monetary(string='Taxes', readonly=True, compute='_amount_all')
	amount_total = fields.Monetary(string='Total', readonly=True, compute='_amount_all')
	partner_id = fields.Many2one('res.partner', related='order_id.partner_id', string='Partner', readonly=True)
	date_order = fields.Datetime(related='order_id.date_order', string='Order Date', readonly=True)
	fiscal_position_id = fields.Many2one('account.fiscal.position', string='Fiscal Position',
										 related='order_id.fiscal_position_id', readonly=True)

	@api.multi
	def save_purchase_order(self):
		self.ensure_one()
		order_lines = []
		for line in self.order_line:
			order_lines.append(line._prepare_order_line(self.order_id))
		self.env['purchase.order.line'].create(order_lines)


class PurchaseOrderLineWizard(models.TransientModel):
	_name = 'purchase.order.line.wizard'
	_description = 'Purchase Order Line Wizard'

	name = fields.Text(string='Description', required=True)
	product_qty = fields.Float(string='Quantity', digits=dp.get_precision('Product Unit of Measure'), required=True)
	date_planned = fields.Datetime(string='Scheduled Date', required=True)
	taxes_id = fields.Many2many('account.tax', string='Taxes',
								domain=['|', ('active', '=', False), ('active', '=', True)])
	product_uom = fields.Many2one('uom.uom', string='Product UoM', required=True)
	product_id = fields.Many2one('product.product', string='Product', domain=[('purchase_ok', '=', True)],
								 change_default=True, required=True)
	price_unit = fields.Float(string='Unit Price', required=True, digits=dp.get_precision('Product Price'))
	price_subtotal = fields.Monetary(compute='_compute_amount', string='Subtotal')
	price_total = fields.Monetary(compute='_compute_amount', string='Total')
	price_tax = fields.Float(compute='_compute_amount', string='Tax')
	order_id = fields.Many2one('purchase.order.wizard', string='Order Reference', required=True, ondelete='cascade')
	company_id = fields.Many2one('res.company', related='order_id.company_id', string='Company', readonly=True)
	partner_id = fields.Many2one('res.partner', related='order_id.partner_id', string='Partner', readonly=True,
								 store=True)
	currency_id = fields.Many2one(related='order_id.currency_id', string='Currency', readonly=True)
	date_order = fields.Datetime(related='order_id.date_order', string='Order Date', readonly=True)
	uom_domain = fields.Char(compute="_compute_uom_domain", readonly=True, store=False)
	product_unit_price = fields.Float('PCE Price')

	@api.depends('product_id')
	def _compute_uom_domain(self):
		for line in self:
			product = line.product_id
			line.uom_domain = dumps(
				[('id', 'in', [product.uom_id.id, product.uom_po_id.id])]
			)

	@api.onchange('product_unit_price')
	def onchange_product_unit_price(self):
		if self.product_unit_price:
			self.price_unit = self.product_unit_price * round(self.product_uom.factor_inv)

	@api.depends('product_qty', 'price_unit', 'taxes_id')
	def _compute_amount(self):
		for line in self:
			vals = line._prepare_compute_all_values()
			taxes = line.taxes_id.compute_all(
				vals['price_unit'],
				vals['currency_id'],
				vals['product_qty'],
				vals['product'],
				vals['partner'])
			line.update({
				'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
				'price_total': taxes['total_included'],
				'price_subtotal': taxes['total_excluded'],
			})

	def _prepare_compute_all_values(self):
		self.ensure_one()
		return {
			'price_unit': self.price_unit,
			'currency_id': self.order_id.currency_id,
			'product_qty': self.product_qty,
			'product': self.product_id,
			'partner': self.order_id.partner_id,
		}

	@api.multi
	def _compute_tax_id(self):
		for line in self:
			fpos = line.order_id.fiscal_position_id or line.order_id.partner_id.property_account_position_id
			# If company_id is set, always filter taxes by the company
			taxes = line.product_id.supplier_taxes_id.filtered(
				lambda r: not line.company_id or r.company_id == line.company_id)
			line.taxes_id = fpos.map_tax(taxes, line.product_id, line.order_id.partner_id) if fpos else taxes

	@api.model
	def _get_date_planned(self, seller, po=False):
		date_order = po.date_order if po else self.order_id.date_order
		if date_order:
			return date_order + relativedelta(days=seller.delay if seller else 0)
		else:
			return datetime.today() + relativedelta(days=seller.delay if seller else 0)

	@api.onchange('product_id')
	def onchange_product_id(self):
		result = {}
		if not self.product_id:
			return result

		# Reset date, price and quantity since _onchange_quantity will provide default values
		self.date_planned = datetime.today().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
		self.price_unit = self.product_qty = 0.0
		self.product_uom = self.product_id.uom_po_id or self.product_id.uom_id

		product_lang = self.product_id.with_context(
			lang=self.partner_id.lang,
			partner_id=self.partner_id.id,
		)
		self.name = product_lang.display_name
		if product_lang.description_purchase:
			self.name += '\n' + product_lang.description_purchase

		self._compute_tax_id()
		self._suggest_quantity()
		self._onchange_quantity()
		return result

	@api.onchange('product_id')
	def onchange_product_id_warning(self):
		if not self.product_id:
			return
		warning = {}
		product_info = self.product_id

		if product_info.purchase_line_warn != 'no-message':
			title = _("Warning for %s") % product_info.name
			message = product_info.purchase_line_warn_msg
			warning['title'] = title
			warning['message'] = message
			if product_info.purchase_line_warn == 'block':
				self.product_id = False
			return {'warning': warning}
		return {}

	@api.onchange('product_qty', 'product_uom')
	def _onchange_quantity(self):
		if not self.product_id:
			return
		params = {'order_id': self.order_id}
		seller = self.product_id._select_seller(
			partner_id=self.partner_id,
			quantity=self.product_qty,
			date=self.order_id.date_order and self.order_id.date_order.date(),
			uom_id=self.product_uom,
			params=params)

		if seller and seller.product_name or seller.product_code:
			self.name = "[{}] {}".format(seller.product_code, seller.product_name)

		if seller or not self.date_planned:
			self.date_planned = self._get_date_planned(seller).strftime(DEFAULT_SERVER_DATETIME_FORMAT)

		if not seller:
			if self.product_id.seller_ids.filtered(lambda s: s.name.id == self.partner_id.id):
				self.price_unit = 0.0
			return

		price_unit = self.env['account.tax']._fix_tax_included_price_company(seller.price,
																			 self.product_id.supplier_taxes_id,
																			 self.taxes_id,
																			 self.company_id) if seller else 0.0
		if price_unit and seller and self.order_id.currency_id and seller.currency_id != self.order_id.currency_id:
			price_unit = seller.currency_id._convert(
				price_unit, self.order_id.currency_id, self.order_id.company_id, self.date_order or fields.Date.today())

		if seller and self.product_uom and seller.product_uom != self.product_uom:
			price_unit = seller.product_uom._compute_price(price_unit, self.product_uom)

		self.price_unit = price_unit

	def _suggest_quantity(self):
		if not self.product_id:
			return
		seller_min_qty = self.product_id.seller_ids \
			.filtered(
			lambda r: r.name == self.order_id.partner_id and (not r.product_id or r.product_id == self.product_id)) \
			.sorted(key=lambda r: r.min_qty)
		if seller_min_qty:
			self.product_qty = seller_min_qty[0].min_qty or 1.0
			self.product_uom = seller_min_qty[0].product_uom
		else:
			self.product_qty = 1.0

	def _prepare_order_line(self, order_id):
		self.ensure_one()
		return {
			'order_id': order_id.id,
			'product_id': self.product_id.id,
			'name': self.name,
			'date_planned': self.date_planned,
			'product_uom': self.product_uom.id,
			'product_qty': self.product_qty,
			'price_unit': self.price_unit,
			'taxes_id': [(6, 0, self.taxes_id.ids)],
			'product_unit_price': self.product_unit_price,
		}
