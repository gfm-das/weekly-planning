"""The areas of the mission, as the pages list them in their "area" drop-down lists.

Used by a missionary's account page (Assigned area), the Historical CSV check (the mapped current area) and Area
mappings.
"""
import sign_in


def current_areas(cur):
    """The areas of the signed-in manager's mission where someone serves now (active area, district and zone), with
    their district and zone: id, name, district_id, district, zone_id, zone. Sorted by zone, district and area."""
    cur.execute("""select a.id,a.name,d.id district_id,d.name district,z.id zone_id,z.name zone
      from public.areas a join public.districts d on d.id=a.district_id
      join public.zones z on z.id=d.zone_id
      where z.mission_id=%s and a.active and d.active and z.active
        and exists (select 1 from public.missionary_assignments ma
                    join public.missionaries m on m.id=ma.missionary_id
                    where ma.area_id=a.id and (ma.end_date is null or ma.end_date>=current_date) and m.status='Active')
      order by z.name,d.name,a.name""", (sign_in.current_mission_id(),))
    return cur.fetchall()
