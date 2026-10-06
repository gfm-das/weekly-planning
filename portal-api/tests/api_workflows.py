"""Rollback-only integration checks against Beta Auth and the actual portal routes.

Run inside portal-api with /tmp/api-test-config.json containing the Beta JWT key.
No notification is sent and no calendar/planning fixture is committed.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,'/app')
import app as api
import reminders

isolated_auth=os.environ.get('PORTAL_TEST_AUTH')=='isolated'
config={} if isolated_auth else json.loads(Path('/tmp/api-test-config.json').read_text())
auth_patch=None
if isolated_auth:
    # Exercise actual database permissions and routes without issuing a JWT.
    # Only this test process replaces the external identity-provider response.
    def fixture_identity(url, headers, timeout):
        encoded=headers['Authorization'].split()[1].split('.')[1]
        identity=json.loads(base64.urlsafe_b64decode(encoded+'=='))['sub']
        return SimpleNamespace(status_code=200,json=lambda:{'id':identity})
    auth_patch=patch.object(api.requests,'get',side_effect=fixture_identity)
    auth_patch.start()
conn=api.connect()
passed=[]

@contextmanager
def transaction():
    conn.cursor_factory=api.RealDictCursor
    with conn.cursor() as cur:
        cur.execute('SET LOCAL ROLE postgres')
    try:
        yield conn
    finally:
        conn.cursor_factory=api.RealDictCursor
        with conn.cursor() as cur:
            cur.execute('SET LOCAL ROLE postgres')

api.db=transaction
reminders.db=transaction
client=api.app.test_client()

def token(user_id):
    enc=lambda v:base64.urlsafe_b64encode(json.dumps(v,separators=(',',':')).encode()).decode().rstrip('=')
    payload=enc({'sub':str(user_id),'role':'authenticated','aud':'authenticated','iat':int(time.time()),'exp':int(time.time())+600})
    raw=enc({'alg':'HS256','typ':'JWT'})+'.'+payload
    if isolated_auth:
        return raw+'.isolated-database-fixture'
    signature=base64.urlsafe_b64encode(hmac.new(config['jwt_secret'].encode(),raw.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    return raw+'.'+signature

def call(user,method,path,body=None,expected=200,headers=None):
    h={'Authorization':'Bearer '+token(user)} if user else {}
    if headers:h.update(headers)
    response=client.open(path,method=method,json=body,headers=h)
    assert response.status_code==expected,(method,path,response.status_code,response.json)
    return response.json

def check(name):
    passed.append(name)
    print('PASS',name)

try:
    users=api.rows(conn,'''SELECT DISTINCT user_id,app_role,leadership_role,area_id,zone_id,district_id
        FROM public.current_user_context WHERE user_active AND mission_id=2''')
    ap=next(u for u in users if u['app_role']=='AP')['user_id']
    ordinary=next((u for u in users if u['app_role']=='MISSIONARY' and not u['leadership_role']),None)
    if ordinary is None:
        # Beta has a normal test login without an area. Use an existing assigned
        # ZL login as an ordinary-companion fixture inside this rollback only.
        ordinary=next(u for u in users if u['app_role']=='MISSIONARY' and u['leadership_role']=='ZL')
        api.rows(conn,'''UPDATE public.leadership_assignments SET end_date=CURRENT_DATE-1
            WHERE missionary_id=(SELECT missionary_id FROM public.user_profiles WHERE id=%s)
            AND start_date<=CURRENT_DATE AND (end_date IS NULL OR end_date>=CURRENT_DATE)''',(ordinary['user_id'],))
    missionary=ordinary['user_id']
    leader=next(u for u in users if u['leadership_role']=='DL')['user_id']
    call(None,'GET','/api/overview',expected=401)
    data=call(ap,'GET','/api/overview')
    assert len(data['planning']['key_indicators'])==6
    assert data['stewardship']['total_areas']>1
    check('authenticated overview and six indicators')
    own=call(missionary,'GET','/api/overview')
    assert own['stewardship'] is None
    target=next(a['area_id'] for a in data['stewardship']['areas'] if a['area_id']!=own['assignment']['area_id'])
    call(missionary,'GET','/api/overview?area_id='+str(target),expected=403)
    check('missionary area drilldown denied outside companionship')
    context=api.context_for(conn,ap)
    now=datetime.now(api.UTC)
    event={'title':'Rollback-only meeting','description':'Test','starts_at':(now-timedelta(hours=2)).isoformat(),
           'ends_at':(now-timedelta(hours=1)).isoformat(),'zone_ids':[context['zone_id']],
           'roles':[],'location':'Test room','meeting_url':'https://example.org/meeting','reminder_minutes':30}
    call(missionary,'POST','/api/events',event,expected=403)
    created=call(ap,'POST','/api/events',event)['event']
    event_id=created['id']
    visible=call(ap,'GET','/api/events')['events']
    assert any(e['id']==event_id for e in visible)
    call(ap,'POST','/api/events/'+event_id+'/attendance',{'occurrence':event['starts_at'],
         'attendance':[{'user_id':str(ap),'attended':True}]})
    assert call(ap,'GET','/api/events/'+event_id+'/attendance?occurrence='+event['starts_at'].replace('+','%2B'))['attendance'][0]['attended']
    check('calendar editor gate, event creation and recorded attendance')
    future=dict(event,starts_at=(now+timedelta(hours=1)).isoformat(),ends_at=(now+timedelta(hours=2)).isoformat())
    fid=call(ap,'POST','/api/events',future)['event']['id']
    call(ap,'POST','/api/events/'+fid+'/attendance',{'occurrence':future['starts_at'],'attendance':[]},expected=400)
    check('attendance blocked before meeting ends')
    # A single UTC instant is expanded in local Berlin time across the autumn DST change.
    sample={'starts_at':datetime.fromisoformat('2026-10-18T10:00:00+02:00'),'ends_at':datetime.fromisoformat('2026-10-18T11:00:00+02:00'),
            'timezone':'Europe/Berlin','recurrence':{'frequency':'weekly','interval':1,'until':'2026-11-02T00:00:00+01:00'}}
    occ=api.occurrences(sample,datetime.fromisoformat('2026-10-17T00:00:00+02:00'),datetime.fromisoformat('2026-11-02T00:00:00+01:00'))
    assert len(occ)==3 and all(e['starts_at'].hour==10 for e in occ)
    check('weekly recurrence preserves Berlin hour across DST')
    dst_event=dict(event,starts_at='2026-10-18T02:30:00+02:00',ends_at='2026-10-18T03:30:00+02:00',
                  recurrence={'frequency':'weekly','interval':1,'until':'2026-11-02T00:00:00+01:00'})
    dst_id=call(ap,'POST','/api/events',dst_event)['event']['id']
    original_datetime=api.datetime
    class Frozen(datetime):
        instant=datetime.fromisoformat('2026-10-25T01:45:00+00:00')
        @classmethod
        def now(cls,tz=None):return cls.instant.astimezone(tz) if tz else cls.instant
    api.datetime=Frozen
    try:
        payload={'occurrence':'2026-10-25T02:30:00+02:00','attendance':[]}
        call(ap,'POST','/api/events/'+dst_id+'/attendance',payload,expected=400)
        Frozen.instant=datetime.fromisoformat('2026-10-25T02:45:00+00:00')
        call(ap,'POST','/api/events/'+dst_id+'/attendance',payload)
    finally:
        api.datetime=original_datetime
    check('ambiguous DST occurrence accepted only after its actual end')
    lc=api.context_for(conn,leader)
    announcement=call(leader,'POST','/api/announcements',{'title':'District update','body':'Rollback test','pinned':True})['announcement']
    assert announcement['district_ids']==[lc['leadership_district_id'] or lc['district_id']]
    aid=announcement['id']
    call(ap,'POST',f'/api/announcements/{aid}/read')
    assert len(call(leader,'GET',f'/api/announcements/{aid}/receipts')['reads'])==1
    call(missionary,'POST','/api/announcements',{'title':'No','body':'No'},expected=403)
    check('leadership announcement scope and read receipts')
    scoped=next(u for u in users if u['district_id']==(lc['leadership_district_id'] or lc['district_id']))
    narrow=call(leader,'POST','/api/announcements',{'title':'Individual update','body':'Private audience',
                'user_ids':[str(scoped['user_id'])]})['announcement']
    assert narrow['zone_ids']==[] and narrow['district_ids']==[] and narrow['area_ids']==[]
    call(leader,'POST','/api/announcements',{'title':'Too wide','body':'No','zone_ids':[lc['zone_id']]},expected=403)
    check('narrow announcement audience preserved without district widening')
    languages=call(missionary,'GET','/api/languages')
    call(missionary,'PUT','/api/languages',{'language':'zz-TEST'},expected=403)
    call(missionary,'PUT','/api/languages',{'language':languages['allowed'][0]})
    check('language changes limited to AP assignments')
    call(ap,'POST','/api/push/subscriptions',{'endpoint':'http://127.0.0.1:5432','keys':{'p256dh':'x','auth':'y'}},expected=400)
    call(ap,'POST','/api/push/subscriptions',{'endpoint':'https://example.org/push','keys':{'p256dh':'x','auth':'y'}},expected=400)
    check('push endpoint provider validation')
    call(ap,'POST','/api/push/subscriptions',{'endpoint':'https://fcm.googleapis.com/push','keys':{'p256dh':'%%%%','auth':'%%%%'}},expected=400)
    call(ap,'POST','/api/push/subscriptions',{'endpoint':'https://fcm.googleapis.com/push','keys':{'p256dh':42,'auth':'abc'}},expected=400)
    check('malformed push keys rejected before scheduling')
    mc=api.context_for(conn,missionary)
    # The week after the current reporting week (Berlin time, as the reminder itself counts): nobody has a plan
    # for it yet, so the reminder is due at 18:00 that Sunday. A fixed date stopped working once its plans were in.
    next_sunday=api.rows(conn,'SELECT public.current_reporting_sunday()+7 AS sunday')[0]['sunday']
    assert not api.rows(conn,'''SELECT 1 FROM public.weekly_area_reports r JOIN public.reporting_weeks w
        ON w.id=r.reporting_week_id WHERE r.area_id=%s AND w.sunday=%s''',(mc['area_id'],next_sunday))
    sunday=datetime.combine(next_sunday,dt_time(18),tzinfo=api.ZoneInfo('Europe/Berlin'))
    due,week=reminders.planning_due(conn,mc,sunday)
    assert due and week==next_sunday.isoformat(),(due,week,next_sunday)
    # A draft saved 3 minutes ago holds the reminder back; 6 minutes ago it does not. The plan is written as the
    # server (no signed-in person), so the plan guard accepts it with these save times.
    api.rows(conn,"SELECT set_config('request.jwt.claims','',true)")
    week_id=api.rows(conn,'''INSERT INTO public.reporting_weeks(sunday) VALUES(%s)
        ON CONFLICT(sunday) DO UPDATE SET sunday=excluded.sunday RETURNING id''',(next_sunday,))[0]['id']
    report=api.rows(conn,'''INSERT INTO public.weekly_area_reports(area_id,reporting_week_id,status,updated_at)
        VALUES(%s,%s,'DRAFT',%s) RETURNING id''',(mc['area_id'],week_id,sunday-timedelta(minutes=3)))[0]['id']
    assert not reminders.planning_due(conn,mc,sunday)[0]
    api.rows(conn,'UPDATE public.weekly_area_reports SET updated_at=%s WHERE id=%s',(sunday-timedelta(minutes=6),report))
    assert reminders.planning_due(conn,mc,sunday)[0]
    assert not reminders.planning_due(conn,mc,sunday-timedelta(minutes=1))[0]
    check('Sunday 18:00 reminder and five-minute activity suppression')
    # UUID arrays must round-trip as lists for explicitly assigned decks.
    service={'X-Service-Key':__import__('os').environ['PORTAL_SERVICE_KEY']}
    rule={'roles':[],'zone_ids':[],'district_ids':[],'user_ids':[str(leader)],'everyone':False}
    result=call(None,'POST','/internal/presentations/access',{'user_id':str(ap),'deck_slug':'rollback-test','operation':'save','rule':rule},headers=service)
    assert isinstance(result['access']['user_ids'],list)
    allowed=call(None,'POST','/internal/presentations/check',{'user_id':str(leader),'deck_slugs':['rollback-test']},headers=service)
    assert allowed['allowed_slugs']==['rollback-test']
    check('individual deck ACL UUID array round-trip')
    mode='isolated identity provider' if isolated_auth else 'real Beta Auth'
    print(f'{len(passed)} workflow groups passed ({mode}); all fixtures rolled back; no push sent.')
finally:
    conn.rollback();conn.close()
    if auth_patch:
        auth_patch.stop()
    if not isolated_auth:
        Path('/tmp/api-test-config.json').unlink(missing_ok=True)
