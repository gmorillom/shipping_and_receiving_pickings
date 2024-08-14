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
WHERE sp.scheduled_date >= (TO_DATE(TO_CHAR(CURRENT_DATE,'YYYY-MM-DD'),'YYYY-MM-DD') - INTERVAL '2 DAYS')
ORDER BY sp.scheduled_date

