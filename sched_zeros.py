#!/usr/bin/env python3

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

import argparse

parser = argparse.ArgumentParser(description="Run the orbital scheduler for one campaign/line.")
parser.add_argument('--date', default="2026-09-21T12:23:30",
                     help="start datetime in ISO format (default: %(default)s)")
parser.add_argument('--delta', default=25000, type=int,
                     help="duration in seconds (default: %(default)s)")
parser.add_argument('--camp', default='schedme',
                     help="campaign name prefix to filter objectives by (default: %(default)s)")
parser.add_argument('--sched-line', type=int, default=15, dest='sched_line',
                     help="schedule line number / generation cycle (default: %(default)s)")
parser.add_argument('--vis-file',
                     default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'visibility_trans2.npz'),
                     dest='visfile',
                     help="file [numpy NPZ] to store visibility calculations (default: %(default)s)")
parser.add_argument('--slew-penalty-weight', type=float, default=0.0, dest='slew_penalty_weight',
                     help="soft preference (0 = off) for scheduling targets with smaller angular "
                          "separation next to each other, e.g. within the same eclipse pass; "
                          "objective points lost per second of required slew time between a "
                          "scheduled neighbour pair (default: %(default)s)")

args = parser.parse_args()
camp = args.camp
date = args.date
delta = args.delta
sched_line = args.sched_line
visfile = args.visfile
slew_penalty_weight = args.slew_penalty_weight

repo=False

import django
django.setup()
from mockat import models,tools

tle_vzlu='''TRANSPORTER-12 OBJECT G
1 62615U 25009G   26263.86389899  .00003966  00000+0  15330-3 0  9993
2 62615  97.3878 342.8058 0005859   6.0294 354.1014 15.26806629 93399'''
tools.tle=tle_vzlu
models.Schedule.objects.filter(line__gte=sched_line).filter(line__lt=sched_line+1).delete() #clear all schedules
# free up objectives that were scheduled by this same generation cycle, so
# regenerating a line doesn't permanently lock them out
models.Objective.objects.filter(scheduled_line=sched_line).update(scheduled_line=None)

import numpy as np
targs_all=models.Target.objects.filter(prior__gte=0)

def select_targets(targs,t0,sun_avoidance=50,moon_avoidance=10):
    '''finds targets that are far enough from Sun and Moon
    '''
    from astropy import coordinates as coor
    from astropy.time import Time
    moon=coor.get_body('moon',Time(t0))
    moon_l=moon.transform_to(coor.GeocentricMeanEcliptic()).lon.degree
    sun_l=tools.sun_pos(t0)

    rabs=lambda df:abs((df+180)%360-180)
    close=lambda l,b:(rabs(moon_l-l)<moon_avoidance)*(abs(b)<moon_avoidance)
    tclose=np.where([close(*t.notes['eclipt_bl']) for t in targs])[0]

    close=lambda l,b:(rabs(sun_l-l)<sun_avoidance)*(abs(b)<sun_avoidance)
    sclose=np.where([close(*t.notes['eclipt_bl']) for t in targs])[0]

    targs_good=[tg for i,tg in enumerate(targs) if not i in sclose and not i in tclose]
    return targs_good

from datetime import datetime,timedelta
t0=datetime.fromisoformat(date)
t1=t0+timedelta(0,delta)

import visibility_loop as vl
import sgp4
m,l1,l2=tle_vzlu.split('\n')
sat=sgp4.api.Satrec.twoline2rv(l1,l2)
vl.our_sat=sat  # needed even on the cache-hit path below, as a live fallback for times outside the precomputed cache

targs_good=select_targets(targs_all.filter(notes__has_key='eclipt_bl'),t0)
targs_good+=list(targs_all.exclude(notes__has_key='eclipt_bl'))
needed_pks=set(t.pk for t in targs_good)

periods=None
newvis=None
cached_pks=None
if os.path.exists(visfile):
    ifile=np.load(visfile,allow_pickle=True)
    newvis=ifile['allvis'].reshape(1,)[0]
    periods=ifile['periods']
    if 'targs_pks' in ifile.files:
        cached_pks=set(ifile['targs_pks'].tolist())

# targets added to the DB (e.g. new ToO transients) after the cache was
# built won't be in it -- fill_eclipses_parallel never sampled them, so a
# cache hit would silently report them as never visible. Recompute for
# everyone needed rather than trying to merge in just the missing ones:
# the recursive bisection in fill_times() samples different timestamps
# depending on which targets are in play, so a partial-target result
# can't be safely merged with the existing one.

print(f'total {len(needed_pks)} targets')
missing_pks = needed_pks - cached_pks if cached_pks is not None else needed_pks
if missing_pks:
    print(f"visibility cache missing {len(missing_pks)} target(s) "
          f"(e.g. {sorted(missing_pks)[:5]}); recomputing for all {len(needed_pks)} targets")
    periods=vl.get_eclipses(tle_vzlu,(t1-t0).total_seconds()*1.1,t0=t0)
    print("%i eclipses, %i mins (asked %i mins)"%(len(periods),(periods[-1][1]-periods[0][0]).total_seconds()//60,(t1-t0).total_seconds()//60))
    vl.allvis={}
    newvis=vl.fill_eclipses_parallel(periods,sorted(needed_pks))
    np.savez(visfile,allvis=newvis,periods=periods,targs_pks=np.array(sorted(needed_pks)))
else:
    print('no new targets calculated')

import orbital_scheduler as ors

if newvis!=None:
    tbase2=np.array([datetime.fromisoformat(a).timestamp() for a in sorted(newvis.keys())])
    spltx2=np.where(tbase2[1:]-tbase2[:-1]>500)[0]
    print(len(spltx2),' intervals')

adap=ors.OrbitalSchedulerAdapter(t0,t1,sun_limit=60,slew_penalty_weight=slew_penalty_weight)
calc=adap.visibility_calc
calc._visibility_cache=newvis
calc._offperiod_cache=np.array([[q.timestamp() for q in p] for p in periods if p[0]<t1]).T
objall=models.Objective.objects.filter(notes__camp__startswith=camp,scheduled_line__isnull=True)
sched2=adap.run(objall)
adap.save_schedules(sched2,sched_line)
adap.show_schedules(sched2)
