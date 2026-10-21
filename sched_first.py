#!/usr/bin/env python3

import os,sys
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
parser.add_argument('--vis-file', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'visibility_trans2.npz'),dest='visfile',
                     help="file [numpy NPZ] to store visibility calculations (default: %(default)s)")
parser.add_argument('--slew-penalty-weight', type=float, default=0.0, dest='slew_penalty_weight',
                     help="soft preference (0 = off) for scheduling targets with smaller angular "
                          "separation next to each other, e.g. within the same eclipse pass; "
                          "objective points lost per second of required slew time between a "
                          "scheduled neighbour pair (default: %(default)s)")
parser.add_argument('--slice', type=int, default=30, dest='slice_size',
                     help="scheduling grid granularity in seconds; must be fine enough that the "
                          "grid does not waste a large fraction of the post-slew slack inside an "
                          "eclipse pass (default: %(default)s)")
parser.add_argument('--max-chunk', type=float, default=600.0, dest='max_chunk',
                     help="split delay==0 objectives into independently schedulable chunks of at "
                          "most this many seconds -- the total exposure can accumulate across "
                          "orbits; 0 restores monolithic blocks (default: %(default)s)")
parser.add_argument('--remainder-boost', type=float, default=2.0, dest='remainder_boost',
                     help="priority multiplier for objectives partially covered by an earlier "
                          "line, so their remainder outranks starting fresh targets; 1 disables "
                          "(default: %(default)s)")
parser.add_argument('--free-split', action='store_true', dest='free_split',
                     help="allow cutting delay==0 objectives anywhere instead of on repeat "
                          "boundaries; tune --max-chunk to tile the eclipse pass (e.g. 620 "
                          "for 2100s passes: 3 chunks + 2 slews)")
parser.add_argument('--cofield-radius', type=float, default=0.25, dest='cofield_radius',
                     help="targets within this radius (deg) of a pointing's primary target are "
                          "exposed simultaneously and all credited; 0.25 = FoV short half-axis "
                          "(safe at any roll), up to 0.45 if roll is steerable; 0 disables "
                          "(default: %(default)s)")
parser.add_argument('--eclipse-margin', type=float, default=30.0, dest='eclipse_margin',
                     help="seconds trimmed off both edges of every eclipse window, guarding "
                          "against TLE staleness and shadow-model boundary error "
                          "(default: %(default)s)")
parser.add_argument('--sun-limit', type=float, default=45.0, dest='sun_avoidance',
                     help="minimum angular distance from the Sun, both for the coarse "
                          "ecliptic-longitude pre-filter and the scheduler's own visibility "
                          "constraint (default: %(default)s)")
parser.add_argument('--skip-verify', action='store_true', dest='skip_verify',
                     help="skip the independent post-run verification gate (umbra, Earth limb, "
                          "sun/moon limits, slew feasibility recomputed from first principles)")
parser.add_argument('--debug', type=int, default=0,
                     help="level of state messaging and checkpoint selection")

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

eclipse_extension=1.1
tle_vzlu='''TRANSPORTER-12 OBJECT G
1 62615U 25009G   26263.86389899  .00003966  00000+0  15330-3 0  9993
2 62615  97.3878 342.8058 0005859   6.0294 354.1014 15.26806629 93399'''
tools.tle=tle_vzlu
models.Schedule.objects.filter(line__gte=sched_line).filter(line__lt=sched_line+1).delete() #clear all schedules
# free up objectives that were scheduled by this same generation cycle, so
# regenerating a line doesn't permanently lock them out; also drop this
# line's exposure contribution from the remainder bookkeeping, both for
# completed objectives (scheduled_line set) and partially covered ones
# (scheduled_line still NULL but notes['done_by_line'] has this line)
for obj in models.Objective.objects.filter(notes__done_by_line__has_key=str(sched_line)):
    obj.notes['done_by_line'].pop(str(sched_line), None)
    if obj.scheduled_line == sched_line:
        obj.scheduled_line = None
    obj.save(update_fields=['notes', 'scheduled_line'])
models.Objective.objects.filter(scheduled_line=sched_line).update(scheduled_line=None)

import numpy as np
targs_all=models.Target.objects.filter(prior__gte=0)

def select_targets(targs,t0,sun_avoidance=50,moon_avoidance=10):
    '''finds targets that are far enough from Sun and Moon
    '''
    from astropy import coordinates as coor
    from astropy.time import Time
    targs=list(targs)
    moon=coor.get_body('moon',Time(t0))
    moon_l=moon.transform_to(coor.GeocentricMeanEcliptic()).lon.degree
    sun_l=tools.sun_pos(t0)

    rabs=lambda df:abs((df+180)%360-180)
    close=lambda l,b:(rabs(moon_l-l)<moon_avoidance)*(abs(b)<moon_avoidance)
    tclose=set(np.where([close(*t.notes['eclipt_bl']) for t in targs])[0].tolist())

    close=lambda l,b:(rabs(sun_l-l)<sun_avoidance)*(abs(b)<sun_avoidance)
    sclose=set(np.where([close(*t.notes['eclipt_bl']) for t in targs])[0].tolist())

    for i in sorted(tclose|sclose):
        t=targs[i]
        l,b=t.notes['eclipt_bl']
        reasons=[]
        if i in sclose:
            reasons.append(f"sun separation {rabs(sun_l-l):.1f} deg < limit {sun_avoidance}")
        if i in tclose:
            reasons.append(f"moon separation {rabs(moon_l-l):.1f} deg < limit {moon_avoidance}")
        print(f"excluded {t.name or '(unnamed)':<20} -- " + "; ".join(reasons))

    targs_good=[tg for i,tg in enumerate(targs) if not i in sclose and not i in tclose]
    print(f"select_targets: excluded {len(sclose|tclose)} of {len(targs)} "
          f"(too close to sun/moon), {len(targs_good)} remain")
    return targs_good

from datetime import datetime,timedelta
t0=datetime.fromisoformat(date)
t1=t0+timedelta(0,delta)

import visibility_loop as vl
import sgp4
m,l1,l2=tle_vzlu.split('\n')
sat=sgp4.api.Satrec.twoline2rv(l1,l2)
vl.our_sat=sat
vl.gdebug=args.debug

# needed even on the cache-hit path below, as a live fallback for times outside the precomputed cache

targs_good=select_targets(targs_all.filter(notes__has_key='eclipt_bl'),t0,args.sun_avoidance)
targs_good+=list(targs_all.exclude(notes__has_key='eclipt_bl')) # targets far from ecliptic, not verified for exclusion angles
needed_pks=set(t.pk for t in targs_good)
print(f'total {len(needed_pks)} targets')

import orbital_scheduler as ors
adap=ors.OrbitalSchedulerAdapter(t0,t1,sun_limit=args.sun_avoidance,slew_penalty_weight=slew_penalty_weight,
                                 slice_size=args.slice_size,max_chunk_seconds=args.max_chunk,
                                 remainder_boost=args.remainder_boost,free_split=args.free_split,
                                 cofield_radius=args.cofield_radius,
                                 eclipse_margin=args.eclipse_margin)

# coverage-aware cache: knows its TLE, its covered time segments, and which
# targets each eclipse period was sampled with, so it recomputes only what
# is actually missing -- both target-set AND time-range aware (the old
# manual np.load/savez handling here only checked the target set, so
# extending --delta without changing --vis-file silently reused a
# too-short cache; see vis_cache.py's module docstring)
import vis_cache as vc
glob_cache=vc.VisibilityCache(path=visfile,tle=tle_vzlu,trust_legacy=True)
glob_cache.ensure(t0,t1,needed_pks,margin=eclipse_extension)
if args.debug==3: sys.exit(0)
adap.visibility_calc.attach_cache(glob_cache)

objall=models.Objective.objects.filter(notes__camp__startswith=camp,scheduled_line__isnull=True)
sched2=adap.run(objall)


if not args.skip_verify:
    # independent gate: everything recomputed from sgp4 + astropy, no shared
    # code with the visibility pipeline that produced the schedule
    import verify_schedule
    problems,bad_idx=verify_schedule.verify(sched2,tle_vzlu,adap)
    if bad_idx:
        # drop just the exposures that failed a per-target physical check
        # (umbra/limb/sun/moon/duration) -- removing one only ever widens
        # the gap for its neighbours, so this can't introduce a new slew
        # problem; re-verify the remainder to confirm rather than assume
        print(f'independent verification: dropping {len(bad_idx)} of {len(sched2)} '
              'exposures that fail a sun/moon/umbra/limb check:')
        for p in problems: print('  -',p)
        sched2=[s for i,s in enumerate(sched2) if i not in bad_idx] 
        problems,bad_idx=verify_schedule.verify(sched2,tle_vzlu,adap)

    if problems:
        print('INDEPENDENT VERIFICATION FAILED -- schedule NOT saved:')
        for p in problems: print('  -',p)
        sys.exit(1)
    else:
        print(f'independent verification passed ({len(sched2)} exposures)')

adap.save_schedules(sched2,sched_line)
adap.show_schedules(sched2)