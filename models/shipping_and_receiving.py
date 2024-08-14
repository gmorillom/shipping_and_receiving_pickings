from odoo import fields, api, models, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
from odoo.exceptions import UserError, ValidationError



class ShippingReceivingWizardLine(models.TransientModel):
    _name = "shipping.receiving.wizard.line"
    _description = "Wizard lines to load shipments in receptions"

    shipping_ref = fields.Char(string='Shipping number',required=True,default='')
    shipping_selected = fields.Boolean(string='Receive',default=False)
    shipping_receiving_wizard_id = fields.Many2one('shipping.receiving.wizard',string='Wizard that loads shipments at receptions')
    

class ShippingReceivingWizard(models.TransientModel):
    _name = "shipping.receiving.wizard"
    _description = "Wizard that loads shipments at receptions"

    def _default_location_id(self):
        return self.env['stock.location'].search([
            ('usage','=','internal'),
        ],limit=1)

    stock_location_id = fields.Many2one('stock.location',string='Destiny',required=True,default=_default_location_id)
    shipping_line_ids = fields.One2many('shipping.receiving.wizard.line','shipping_receiving_wizard_id',string='Shippings')

    @api.onchange('stock_location_id')
    def _get_shipping_refs(self):
        """ Domain to show the shipments that can be received, use the same query as from the transfer
            to verify available shipments, but does not filter those fully received

            Generate the wizard lines
        """
        today = fields.Date.context_today(self)
        # Only select newest transferss
        start_date = today - (timedelta(days=10) if self.env.user.has_group('shipping_and_receiving_pickings.shipping_and_receiving_picking_manager') else timedelta(days=2))

        sql = """
            SELECT sp.id, spt.name, sp.name, sl.complete_name, sld.complete_name, sp.scheduled_date
            FROM stock_picking AS sp
            INNER JOIN (
                SELECT id, complete_name
                FROM stock_location
                WHERE usage = 'internal'
            ) AS sl ON sl.id = sp.location_id 
            INNER JOIN (
                SELECT id, complete_name
                FROM stock_location
                WHERE usage = 'transit'
            ) AS sld ON sld.id = sp.location_dest_id  
            INNER JOIN stock_picking_type AS spt ON spt.id = sp.picking_type_id AND spt.code = 'internal'
            WHERE sp.scheduled_date >= '{} 00:00:00' AND sp.complete_receiving = false
            ORDER BY sp.scheduled_date
        """.format(start_date.strftime('%Y-%m-%d'))

        self.env.cr.execute(sql)
        # (picking_id,picking_type_name,picking_name,location_id,location_dest_id,fecha fecha)
        valid_shippings = self.env.cr.fetchall()
        warehouses = self.env['stock.warehouse'].search([
            ('branch_id','=',self.stock_location_id.branch_id.id)
        ]).mapped('code')
        _names = []

        for shipping in valid_shippings:
            for wh in warehouses:
                if wh in shipping[4]:
                    _names.append(shipping[2])

        _names = list(set(_names))
        _lines = []
        self.shipping_line_ids = [(5,0,0)]

        for _n in _names:
            _lines.append((0,0,{'shipping_ref':_n}))

        self.shipping_line_ids = _lines


    def action_confirm(self):
        """ Create a reception with the information of the destination branch and with the information 
            of the shipping products, use the methods that stock.picking has already defined
        """
        if self.env.context.get('active_id',0) == 0:
            raise ValidationError('No active record found')
        
        type_id = self.env['stock.picking.type'].browse(self.env.context.get('active_id',0))

        if not type_id:
            raise ValidationError('An internal transfer operation type cannot be found')
        
        line_id = self.shipping_line_ids.filtered(lambda l: l.shipping_selected)

        if len(line_id) != 1:
            raise ValidationError('You can only select one shipping by one')
        
        sql = """
            SELECT location_dest_id 
            FROM stock_picking 
            WHERE name = '{}'
        """.format(line_id.shipping_ref)
        self.env.cr.execute(sql)
        shipping_id = self.env.cr.fetchall()
        
        picking_id = self.env['stock.picking'].create({
            'picking_type_id': type_id.id,
            'location_id': shipping_id[0],
            'location_dest_id': self.stock_location_id.id,
            'partner_id': self.env.company.partner_id.id,
            'branch_id': type_id.branch_id.id,
            'company_id': self.env.company.id,
            'immediate_transfer': False
        })

        picking_id.with_context(allow_receive_shipping=True)._change_require_shipping_id()
        picking_id.shipping_name = line_id.shipping_ref
        picking_id._change_origin_for_shipping_id()

        res = {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "stock.picking",
            "res_id": picking_id.id,
        }

        
        return res