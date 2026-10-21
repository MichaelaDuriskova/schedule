from . import models

def update_from_GUANO(lim=10):
    from swifttools.swift_too import GUANO
    last=models.Fermi.object.latest().date
    rep=GUANO(begin=last.strftime('%Y-%m-%d'),limit=lim)
    return rep

def create_from_line(l):
    from datetime import datetime,timezone
    idate=datetime.fromisoformat('20'+l[1].replace('/','-')+'T'+l[2][:8]).replace(tzinfo=timezone.utc)
    return models.Fermi(id=l[0],date=idate,pRA=float(l[4]),pdec=float(l[5]),inten=float(l[6]),notes={'type':l[4]})
    
def new_load(process=True):
    import os
    flst=[a for a in os.listdir(models.Observation.jpath) if a[-5:]=='.json']
    done=[a.jfile for a in models.Observation.objects.all()]
    flst=sorted([f for f in flst if not f in done and f[0]=='r'])
    if not process: return flst
    for f in flst:
        oname='obs '+f[1:7]
        if f.find('_')>0:
            oname+=' '+f[f.find('_')+1:-5]
        ob=models.Observation(jfile=f,desc=oname) 
        ob.read() 
        ob.updates()
        print(f'added {oname}: {ob.nspec} spectra ')
