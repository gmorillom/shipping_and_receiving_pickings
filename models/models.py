# -*- coding: utf-8 -*-

# from odoo import models, fields, api

from odoo import models, fields, api
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError, ValidationError
from odoo import api, SUPERUSER_ID
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

class StockPicking(models.Model):
    _inherit = "stock.picking"

    permit_to_edit = fields.Boolean(default=False)
    complete_receiving = fields.Boolean(string='Is totally received',default=False)
    shipping_name = fields.Char(string='Shipping to receive',default='')
    require_shipping_id = fields.Boolean(string='Require shipping',default=False)
    show_validate_assigned = fields.Boolean(compute='_compute_show_validate',help='', default=True)

    @api.depends('immediate_transfer', 'state')
    def _compute_show_check_availability(self):
        """ According to `picking.show_check_availability`, the "check availability" button will be
        displayed in the form view of a picking.
        """
        for picking in self:
            
            if (picking.immediate_transfer or picking.state not in ('confirmed', 'waiting', 'assigned')):
                picking.show_check_availability = False
                continue
            
            if (picking.state == 'assigned' and picking.picking_type_id.id in (12,31)):
                
                if self.env.user.has_group('base.group_system'):
                    picking.show_check_availability = any(
                        move.state in ('waiting', 'confirmed', 'partially_available') and
                        float_compare(move.product_uom_qty, 0, precision_rounding=move.product_uom.rounding)
                        for move in picking.move_lines
                        )
                else:
                    picking.show_check_availability = False
                    continue
            
            picking.show_check_availability = any(
                move.state in ('waiting', 'confirmed', 'partially_available') and
                float_compare(move.product_uom_qty, 0, precision_rounding=move.product_uom.rounding)
                for move in picking.move_lines
                )
        

    @api.depends('state')
    def _compute_show_validate(self):
        for picking in self:
            if not (picking.immediate_transfer) and picking.state == 'draft':
                picking.show_validate = False
            elif picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                picking.show_validate = False
            else:
                
                if not (picking.state == 'assigned' and picking.picking_type_id.id in (12,31)):
                    picking.show_validate = True
                
                else:
                    if picking.state == 'assigned' and picking.picking_type_id.id in (12,31) and self.env.user.has_group('base.group_system'):
                        picking.show_validate = True

    def action_confirm(self):
        """ Restrict transfer with same origin and destiny """
        resp = super(StockPicking, self).action_confirm()
        code = self.picking_type_id.warehouse_id.code

        if(self and self.location_id.id == self.location_dest_id.id):
            raise UserError("Origin and destiny can't be the same. \n Please, edit to continue.")
        
        if code and code in self.location_dest_id.complete_name and  self.location_dest_id.usage == 'transit' and not self.env.user.has_group('shipping_and_receiving_pickings.receipt_wihout_number_tracking_admin'):
            raise UserError("Origin location and transit location belongs to the same warehouse. \n Please, edit to continue.")
        
        return resp
    
    
    def button_validate(self):
        """ Mark the shipping as totally received """
        res = super(StockPicking,self).button_validate()

        if self and isinstance(self.shipping_name,str) and len(self.shipping_name) > 0 and self.state in ('done'):
            sql = """
                SELECT product_id, qty_done 
                FROM stock_move_line
                WHERE reference = '{}' AND state IN ('done')
            """.format(self.shipping_name)
            self.env.cr.execute(sql)
            shipping = self.env.cr.fetchall()

            sql = """
                SELECT sml.product_id, sml.qty_done
                FROM stock_move_line AS sml
                INNER JOIN stock_move AS sm ON sm.id = sml.move_id
                INNER JOIN stock_picking AS sp ON sp.id = sm.picking_id
                WHERE sml.reference = '{}' AND sml.reference ilike '{}' AND sml.state IN ('done');
            """.format(self.id,self.shipping_name,self.shipping_name)
            self.env.cr.execute(sql)
            receiving = self.env.cr.fetchall()
            shipping_dict = {}

            for line in shipping:
                key = line[0]
                if key in shipping_dict:
                    shipping_dict[key] += line[1]
                else:
                    shipping_dict[key] = line[1]

            receiving_dict = {}

            for line in receiving:
                key = line[0]
                if key in receiving_dict:
                    receiving_dict[key] += line[1]
                else:
                    receiving_dict[key] = line[1]

            complete_receiving = True

            for line in self.move_line_ids_without_package:
                key = line.product_id.id
                if key in receiving_dict and key in shipping_dict and shipping_dict[key] - receiving_dict[key] != 0:
                    complete_receiving = False

            sql = """
                UPDATE stock_picking SET complete_receiving = {}
                WHERE name = '{}'
            """.format('true' if complete_receiving else 'false',self.shipping_name)
            self.env.cr.execute(sql)

        return res
    
    def _get_shipping_domain(self):
        """ Domain to show the shipments that can be received """
        today = fields.Date.context_today(self)
        start_date = today - (timedelta(days=10) if self.env.user.has_group('shipping_and_receiving_pickings.shipping_and_receiving_picking_manager') else timedelta(days=2))

        sql = """
            SELECT sp.id, spt.name, sp.name, sl.complete_name, sld.complete_name, sp.scheduled_date
            FROM stock_picking AS sp
            INNER JOIN (
                SELECT id, complete_name, is_delivery_order
                FROM stock_location
                WHERE usage = 'internal' AND is_delivery_order=false OR is_delivery_order IS NULL
            ) AS sl ON sl.id = sp.location_id 
            INNER JOIN (
                SELECT id, complete_name
                FROM stock_location
                WHERE usage = 'transit' AND is_delivery_order=false OR is_delivery_order IS NULL
            ) AS sld ON sld.id = sp.location_dest_id  
            INNER JOIN stock_picking_type AS spt ON spt.id = sp.picking_type_id AND spt.code = 'internal'
            WHERE sp.scheduled_date >= '{} 00:00:00' AND sp.complete_receiving = false
            ORDER BY sp.scheduled_date
        """.format(start_date.strftime('%Y-%m-%d'))

        self.env.cr.execute(sql)
        # (picking_id,picking_type_name,picking_name,location_id,location_dest_id,fecha fecha)
        valid_shippings = self.env.cr.fetchall()
        warehouses = self.env['stock.warehouse'].search([
            ('branch_id','=',self.branch_id.id)
        ]).mapped('code')
        _ids = []

        for shipping in valid_shippings:
            for wh in warehouses:
                if wh in shipping[4]:
                    _ids.append(shipping[0])

        criterial = [
            ('id','in',list(set(_ids)))
        ]
        
        return criterial

    @api.onchange('location_id','location_dest_id','picking_type_id')
    def _change_require_shipping_id(self):
        """ Check if it is allowed to receive shipments from the current view """
        is_shipping_receive = (self.location_id and self.location_id.usage == 'transit' and not self.location_id.return_location) \
            and (self.location_dest_id and self.location_dest_id.usage == 'internal') \
            and (self.picking_type_id and self.picking_type_id.code == 'internal')

        if is_shipping_receive and not self.env.context.get('allow_receive_shipping',False) and not self.env.user.has_group('shipping_and_receiving_pickings.receipt_wihout_number_tracking_admin'):
            raise UserError('Shipment receipts can only be made from the Receive button in the Inventory Summary')

        """ Check if these are receipts from transit to require or not select a shipment """
        self.require_shipping_id = is_shipping_receive
        # Check if the person has the permissions for the field to be required
        if self.env.user.has_group('shipping_and_receiving_pickings.receipt_wihout_number_tracking_admin') or (self.env.user.has_group('base.group_system')):
            self.permit_to_edit = True
        
    @api.onchange('shipping_name')
    def _change_origin_for_shipping_id(self):
  
        # Import shipping information
        if self.shipping_name:
            
            self.origin = self.shipping_name
            
            # If there have already been transfers with the same imported order, then it is notified with a warning
            if (self.check_other_shipping()):
                self.import_partial_shipping()
            else:
                self.import_shipping(button=False)     
        else:
            self.origin = ''
            self.sudo().move_lines = [(5, 0, 0)]  # To delete all motion lines
            self.sudo().move_line_ids = [(5, 0, 0)]  # To delete all motion line IDs
            self.origin = ''
    


    def check_other_shipping(self):
        
        check_shipping = self.env['stock.picking'].search([('name', '=', self.shipping_name),
                                                           ('backorder_id', '=', False)])

        return len(check_shipping) > 1
    
    def import_partial_shipping(self):
        
        check_shipping = self.env['stock.picking'].search([('name', '=', self.shipping_name)])
        check_shipping_names = ', '.join([order.name for order in check_shipping])
        
    def import_shipping(self, button=True):

        today = fields.Date.context_today(self)
        start_date = today - (timedelta(days=7) if self.env.user.has_group('shipping_and_receiving_pickings.shipping_and_receiving_picking_manager') else timedelta(days=2))
        completely_received = True
        
        # First we look for the shipping
        self.env.cr.execute('SELECT id, name, location_dest_id ,scheduled_date, state FROM stock_picking WHERE name = %s', (self.shipping_name if self.shipping_name else '',))
        shipping_aux = self.env.cr.fetchone()

        # Once the shipment has been searched, it is verified if it is a valid shipment
        if shipping_aux and shipping_aux[4] == 'done' and shipping_aux[2]  == self.location_id.id and shipping_aux[3].date() >= start_date:
            
            # Now we need to check if the user has permission to view this submission
            # For this we must first get the name of the destination warehouse
            location_dest_name = self.env['stock.location'].browse(shipping_aux[2]).complete_name
            band = False
            # We search all the warehouses to know the warehouse code and the branch identifier
            warehouses = self.env['stock.warehouse'].search([])
            # We obtain the identifier of the branches to which the user has access
            allowed_branches = self.env.user.branch_ids.mapped('id')
            
            # Now we go through all the warehouses, see if the code is found in the name of the
            # destination warehouse and if the branch to which the warehouse belongs is among the branches
            # allowed to the user.
            for warehouse in warehouses:
                if warehouse['code'] in location_dest_name and warehouse['branch_id'].id in allowed_branches:
                    # If the condition is met, then the user has access to the shipment
                    band = True
                    break
            # With everything already verified, if the user has access to the shipment, then it is prepared
            # shipping information
            if band:

                # The delivery note fields are imported into the order
                self.move_ids_without_package = [(2,t.id) for t in self.move_ids_without_package]
                [(5,0,0)]

                # We look for the products that will be received
                sql_sent_shipping = """
                    SELECT sm.product_id, sm.qty_done, product_uom_id, pt.name, sl.complete_name
                    FROM stock_move_line AS sm
                    INNER JOIN product_product AS pp ON pp.id = sm.product_id
                    INNER JOIN product_template AS pt ON pt.id = pp.product_tmpl_id
                    INNER JOIN (SELECT name, id, scheduled_date, location_dest_id FROM stock_picking) AS sp ON sm.picking_id = sp.id
                    INNER JOIN (SELECT id, complete_name FROM stock_location) AS sl ON sp.location_dest_id = sl.id
                    WHERE sp.name = '{}'
                """.format(self.shipping_name)
                self.env.cr.execute(sql_sent_shipping)
                shipping_sent_lines = self.env.cr.fetchall()

                # We look for the products that have already been received and calculate the quantity that has already been received
                sql_received_shippings = """   
                    SELECT product_id, SUM(qty_done) FROM
                    (SELECT id, name, origin, state FROM public.stock_picking WHERE origin = '{}' AND state = 'done') AS sp
                    INNER JOIN
                    (SELECT id,  product_id, qty_done, picking_id FROM public.stock_move_line) AS sm
                    ON sm.picking_id = sp.id
                    GROUP BY product_id;
                """.format(self.shipping_name)
                self.env.cr.execute(sql_received_shippings)
                shipping_received_lines = self.env.cr.fetchall()

                # We create a dictionary with the products shipped and their quantities shipped
                shipping_lines = {}
                for shipping_line in shipping_sent_lines:
                    shipping_lines[shipping_line[0]] = {
                        'product_qty_done' : shipping_line[1],
                        'product_uom' : shipping_line[2],               
                        'name' : shipping_line[3]
                        }

                # We subtract the quantities that have already been received from the products shipped
                for shipping_line in shipping_received_lines:
                    if shipping_line[0] in shipping_lines:
                        shipping_lines[shipping_line[0]]['product_qty_done'] -= shipping_line[1]

                # Now we actually load the data into the system
                for shipping_product_id in shipping_lines.keys():
                    
                    # Each key is the id of a product that is going to be received, so we obtain
                    # the data of that product and we check if there is anything left to receive.
                    # If there is something left to receive, then a movement and a line of movement are created
                    # with the amount remaining to be received
                    product_values = shipping_lines[shipping_product_id]

                    if product_values['product_qty_done'] > 0:

                        completely_received = False

                        move = { 
                            "product_id" : shipping_product_id,
                            'product_uom_qty' : product_values['product_qty_done'],
                            'product_uom' : product_values['product_uom'],
                            'picking_id' : self.id,
                            'quantity_done' : 0,
                            'state' : 'draft',
                            'name' : product_values['name'],
                            'location_id' :  self.location_id.id,
                            'location_dest_id' : self.location_dest_id.id,
                               
                        }
                                            
                        stock_move = self.env['stock.move'].sudo().create(move)
                        stock_move.is_quantity_done_editable = True
                        
                        move_line = { 
                            "product_id" : shipping_product_id,
                            'qty_done': product_values['product_qty_done'],
                            'product_uom_id' : product_values['product_uom'],
                            'picking_id' : self.id,
                            'state' : 'draft',
                            'move_id': stock_move.id,
                            'location_id' :  self.location_id.id,
                            'location_dest_id' : self.location_dest_id.id,                            
                        }
                        stock_move_line = self.env['stock.move.line'].sudo().create(move_line)
        
        # If any of the previous conditions were not met, then the user is notified.
        # Else was not used because the flag that checks if the user has access to that branch
        # It is not part of the main if
        
        if (not shipping_aux or shipping_aux[4] != 'done' or not int(shipping_aux[2]) == int(self.location_id.id) or not band or not shipping_aux[3].date() >= start_date):

            self.sudo().move_lines = [(5, 0, 0)]  # To delete all motion lines
            self.sudo().move_line_ids = [(5, 0, 0)]  # To delete all motion line IDs

            if button:
                raise UserError('The indicated shipment was not found')
        # If the shipment has already been completely received, then the user is notified  
        if completely_received and button:

            raise UserError('The shipment has already been completely received')
    

class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    
    def action_receive_shipping(self):
        """ Throws a wizard for receive shippings """
        res = self._get_action('shipping_and_receiving_pickings.action_view_shipping_receiving_wizard')
        
        return res
    

