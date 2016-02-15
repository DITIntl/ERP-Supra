import time
import netsvc
import openerp.exceptions
import decimal_precision as dp
import re
from tools.translate import _
from osv import fields, osv
from datetime import datetime, timedelta
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DATETIME_FORMATS_MAP, float_compare

class order_preparation(osv.osv):
	_inherit = "order.preparation"
	_description = "Order Packaging"
	_columns = {
		'poc': fields.char('Customer Reference', size=64,track_visibility='onchange',readonly=True, states={'draft': [('readonly', False)]}),
		'name': fields.char('Reference', required=True, size=64, select=True, readonly=True, states={'draft': [('readonly', False)]}),
		'sale_id': fields.many2one('sale.order', 'Sale Order', select=True, required=True, readonly=True, domain=['|', ('quotation_state','=','win'),('state','in',['progress','manual'])], states={'draft': [('readonly', False)]}),
		'picking_id': fields.many2one('stock.picking', 'Delivery Order', required=False, domain="[('sale_id','=', sale_id), ('state','not in', ('cancel','done'))]", readonly=True, states={'draft': [('readonly', False)]},track_visibility='always'),
		'duedate' : fields.date('Delivery Date', readonly=True, states={'draft': [('readonly', False)]},track_visibility='onchange'),
		'location_id':fields.many2one('stock.location',required=True,string='Product Location',readonly=True, states={'draft': [('readonly', False)]}),

	}

	_order = "id desc"
	
	def preparation_done(self, cr, uid, ids, context=None):
		val = self.browse(cr, uid, ids)[0]

		for x in val.prepare_lines:
			if x.sale_line_material_id.id==False:
				raise openerp.exceptions.Warning("OP Line Tidak Memiliki ID Material Line")
		return super(order_preparation, self).preparation_done(cr, uid, ids, context=context)

	def sale_change(self, cr, uid, ids, sale, loc=False, context=None):

		so_material_line = self.pool.get('sale.order.material.line')
		obj_op_line = self.pool.get('order.preparation.line')
		obj_op = self.pool.get('order.preparation')
		obj_dn_line_mat = self.pool.get('delivery.note.line.material')
		obj_dn_line_mat_ret = self.pool.get('delivery.note.line.material.return')
		obj_move = self.pool.get('stock.move')

		if sale:
			res = {}; line = []
			data = self.pool.get('sale.order').browse(cr, uid, sale)
			
			res['poc'] = data.client_order_ref
			res['partner_id'] = data.partner_id.id
			res['duedate'] = data.delivery_date
			res['partner_shipping_id'] = data.partner_shipping_id.id

			location = []
			for x in data.order_line:
				if x.material_lines == []:
					raise openerp.exceptions.Warning("SO Material Belum di Definisikan")

				if loc:
					material_lines=so_material_line.search(cr,uid,[('sale_order_line_id', '=' ,x.id), ('picking_location', '=' , loc)])
				else:
					material_lines=so_material_line.search(cr,uid,[('sale_order_line_id', '=' ,x.id)])

				for y in so_material_line.browse(cr, uid, material_lines):
					# Cek Material Line Dengan OP Line
					nilai= 0
					op_line = obj_op_line.search(cr,uid,[('sale_line_material_id', '=' ,y.id)])
					for l in obj_op_line.browse(cr, uid, op_line):
						# Cek Status OP 
						op=obj_op.browse(cr, uid, [l.preparation_id.id])[0]
						product_return = 0
						search_dn_lm=obj_dn_line_mat.search(cr, uid, [('op_line_id', '=' , [l.id])])
						if search_dn_lm:
							search_cek_return=obj_dn_line_mat_ret.search(cr, uid, [('delivery_note_line_material_id', '=' , [search_dn_lm])])
							# Cek DN Line Material Return
							for rn in obj_dn_line_mat_ret.browse(cr, uid, search_cek_return):
								if rn.stock_move_id.state == 'done':
									product_return += rn.stock_move_id.product_qty

						if op.state <> 'cancel':
							nilai += l.product_qty - product_return
					if nilai < y.qty:

						location += [y.picking_location.id]

						line.append({
									 'product_id' : y.product_id.id,
									 'product_qty': y.qty - nilai,
									 'product_uom': y.uom.id,
									 'name': y.desc,
									 'sale_line_material_id':y.id
						})
			res['prepare_lines'] = line
			return  {'value': res,'domain': {'location_id': [('id','in',tuple(location))]}}

	def preparation_confirm(self, cr, uid, ids, context=None):
		val = self.browse(cr, uid, ids)[0]

		obj_op_line = self.pool.get('order.preparation.line')
		obj_op = self.pool.get('order.preparation')
		obj_dn_line_mat = self.pool.get('delivery.note.line.material')
		obj_dn_line_mat_ret = self.pool.get('delivery.note.line.material.return')
		obj_move = self.pool.get('stock.move')

		for x in val.prepare_lines:
			nilai= 0
			op_line=obj_op_line.search(cr,uid,[('sale_line_material_id', '=' ,x.sale_line_material_id.id)])
			
			for l in obj_op_line.browse(cr, uid, op_line):
				op=obj_op.browse(cr, uid, [l.preparation_id.id])[0]

				product_return = 0
				search_dn_lm=obj_dn_line_mat.search(cr, uid, [('op_line_id', '=' , [l.id])])
				if search_dn_lm:
					search_cek_return=obj_dn_line_mat_ret.search(cr, uid, [('delivery_note_line_material_id', '=' , [search_dn_lm])])
					# Cek DN Line Material Return
					for rn in obj_dn_line_mat_ret.browse(cr, uid, search_cek_return):
						if rn.stock_move_id.state == 'done':
							product_return += rn.stock_move_id.product_qty

				if op.state <> 'cancel':
					nilai += l.product_qty - product_return

			if x.sale_line_material_id.id:
				if val.location_id.id <> x.sale_line_material_id.picking_location.id:
					raise openerp.exceptions.Warning("Product Location Tidak Sama")

				so_material_line=self.pool.get('sale.order.material.line').browse(cr, uid, [x.sale_line_material_id.id])[0]
				mm = ' ' + so_material_line.product_id.default_code + ' '
				msg = 'Product' + mm + 'Melebihi Order.!\n'

				if nilai > so_material_line.qty:
					raise openerp.exceptions.Warning(msg)

		return super(order_preparation, self).preparation_confirm(cr, uid, ids, context=context)
		
order_preparation()

class order_preparation_line(osv.osv):
	_inherit = "order.preparation.line"
	_columns = {
		'sale_line_material_id': fields.many2one('sale.order.material.line', 'Material Ref'),
	}

order_preparation_line()