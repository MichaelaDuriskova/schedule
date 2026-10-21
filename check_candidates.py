#!/usr/bin/env python3
"""Diagnostic (read-only): for every target currently in the schedme
candidate pool (unscheduled Objectives in this campaign), show whether it
has ANY usable visibility window in [--date, --date+--delta), and if not,
why -- too close to Sun/Moon, or below the Earth limb, checked at every
eclipse pass in range. Does not touch the DB or save anything.

Run with the SAME --date/--delta/--camp/--vis-file as your sched_first.py
call, so it reuses the already-computed .npz cache (run sched_first.py
once first with that vis-file if it doesn't exist yet).
"""
import os,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--date', default="2026-09-21T12:23:30")
parser.add_argument('--delta', default=25000, type=int)
parser.add_argument('--camp', default='schedme')
parser.add_argument('--vis-file', dest='visfile',
                     default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'visibility_trans2.npz'))
args = parser.parse_args()

import django
django.setup()
from mockat import models, tools

tle_vzlu='''TRANSPORTER-12 OBJECT G
1 62615U 25009G   26263.86389899  .00003966  00000+0  15330-3 0  9993
2 62615  97.3878 342.8058 0005859   6.0294 354.1014 15.26806629 93399'''
tools.tle=tle_vzlu

import numpy as np, math, warnings
from datetime import datetime,timedelta

t0=datetime.fromisoformat(args.date)
t1=t0+timedelta(0,args.delta)

if not os.path.exists(args.visfile):
    print(f"vis-file {args.visfile} not found -- run sched_first.py once with this "
          "--date/--delta/--vis-file first so the cache exists")
    sys.exit(1)

ifile=np.load(args.visfile,allow_pickle=True)
newvis=ifile['allvis'].reshape(1,)[0]
periods=ifile['periods']

import orbital_scheduler as ors
adap=ors.OrbitalSchedulerAdapter(t0,t1,sun_limit=60)
calc=adap.visibility_calc
calc._visibility_cache=newvis
calc._offperiod_cache=np.array([[q.timestamp() for q in p] for p in periods if p[0]<t1]).T

objall=models.Objective.objects.filter(notes__camp__startswith=args.camp,scheduled_line__isnull=True)
targets=list({obj.target.pk: obj.target for obj in objall}.values())

from sgp4.api import Satrec, jday
from astropy.time import Time
from astropy.coordinates import get_sun, get_body, SkyCoord
import astropy.units as u

lines=[ln.strip() for ln in tle_vzlu.strip().splitlines() if ln.strip()]
sat=Satrec.twoline2rv(lines[-2],lines[-1])
R_EQ=6378.137

def sat_r(dt):
    dt=dt.replace(tzinfo=None) if dt.tzinfo else dt
    jd,fr=jday(dt.year,dt.month,dt.day,dt.hour,dt.minute,dt.second+dt.microsecond*1e-6)
    err,r,_=sat.sgp4(jd,fr)
    return np.array(r)

def above_limb(dt,coord):
    r=sat_r(dt); rn=np.linalg.norm(r)
    tgt=coord.cartesian.xyz.value
    gamma=math.degrees(math.acos(np.clip(np.dot(tgt,-r/rn),-1.0,1.0)))
    rho=math.degrees(math.asin(R_EQ/rn))
    return gamma>rho+calc.earth_limb

print(f"{len(targets)} candidate targets in camp '{args.camp}':\n")
for t in sorted(targets,key=lambda t:t.name or ''):
    windows=calc.compute_windows(t,t0,t1,min_window_duration=60.0).toTupleList()
    if windows:
        total=sum((b-a).total_seconds() for a,b in windows)
        print(f"  OK       {t.name or '?':<20} {len(windows)} window(s), {total:.0f}s total")
        for a,b in windows:
            print(f"             {a.strftime('%m-%d %H:%M:%S')} -> {b.strftime('%H:%M:%S')} "
                  f"({(b-a).total_seconds():.0f}s)")
        continue

    coord=SkyCoord(t.pRA*u.deg,t.pdec*u.deg)
    reasons=set()
    for p0,p1 in periods:
        if p1<t0 or p0>t1: continue
        mid=p0+(p1-p0)/2
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            tmid=Time(mid.replace(tzinfo=None) if mid.tzinfo else mid)
            sun_sep=get_sun(tmid).separation(coord).degree
            moon_sep=get_body('moon',tmid).separation(coord).degree
        if sun_sep<calc.sun_limit:
            reasons.add(f"sun {sun_sep:.0f} < {calc.sun_limit}")
        if moon_sep<calc.moon_limit:
            reasons.add(f"moon {moon_sep:.0f} < {calc.moon_limit}")
        if not above_limb(mid,coord):
            reasons.add(f"below earth limb (limit {calc.earth_limb})")
    reason=', '.join(sorted(reasons)) if reasons else "no reason found in any eclipse pass -- check cache coverage"
    print(f"  EXCLUDED {t.name or '?':<20} no visibility window -- {reason}")
