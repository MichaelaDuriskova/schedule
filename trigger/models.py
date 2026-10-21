from django.db import models

# Create your models here.
def emptyjson():
    return {"type":"none"}

class Observation(models.Model):
    jfile = models.FilePathField(path="/home/limu/Data/Alpha/")
    desc = models.CharField(max_length=200)
    dfrom = models.DateTimeField('from',blank=True)
    dto = models.DateTimeField('to',blank=True)
    nspec = models.IntegerField(default=0)

    jpath="/home/limu/Data/Alpha/"

    def read(self):
        import json
        try:
            self.data=json.load(open(self.jpath+self.jfile))
        except:
            try:
                inp=open(self.jpath+self.jfile).strip().replace('\n',',\n')
                self.data=json.loads('['+inp+']')
            except:
                self.data=[]
                for a in open(self.jpath+self.jfile).read().split('\n'):
                    if a.find('{')<0: continue
                    try:
                        a=a.strip()
                        if a[-1]==',': a=a[:-1]
                        self.data.append(eval(a))
                    except:
                        print("problem eval. "+a)
            return len(self.data)

    def updates(self):
        from datetime import datetime
        import pytz
        utc=pytz.timezone('UTC')
        for beg in self.data:
            if not 'utc' in beg:
                if not 'mid' in beg:
                    continue
                beg=beg['mid']
            if int(beg['utc'][:4])<2000: continue
            self.dfrom=datetime.fromisoformat(beg['utc']).replace(tzinfo=utc)
            break
        for end in self.data[::-1]:
            if not 'utc' in end:
                if not 'mid' in end:
                    continue
                end=end['mid']
            self.dto=datetime.fromisoformat(end['utc']).replace(tzinfo=utc)
            break
        #imax=len(self.data)-1
        #while not 'utc' in self.data[imax]:imax-=1
        cnt=0
        for d in self.data:
            if d.get('type','')=='spectrum': cnt+=1
        self.nspec=cnt
        self.save()

    def get_matches(self,objects,save=True):
        select=objects.filter(date__gte=self.dfrom).filter(date__lte=self.dto)
        if save:
            for s in select:
                s.observed=self
                s.save()
        return select

    def get_data(self,drange=[],min_len=5):
        import numpy as np
        times=[]
        spec=[]
        if not hasattr(self,'data'): self.read()
        act_len=0

        for d in self.data:
            if d.get('type','')!='spectrum': continue
            if not 'data' in d: continue
            if len(d['data'])<min_len: continue
            times.append(d['mid'].get('time',0))
            if act_len==0: act_len=len(d['data'])
            elif act_len>len(d['data']): act_len=len(d['data'])
            spec.append(d['data'])
        self.times=np.array(times)-times[0]
        self.spec=np.array([s[:act_len] for s in spec])
        return self.spec

class Fermi(models.Model):
    trigid = models.CharField(max_length=200)
    date = models.DateTimeField('triggered')
    pRA = models.FloatField('RAsc',blank=True)
    pdec = models.FloatField('Decl',blank=True)
    inten = models.FloatField('intensity',default=0)
    notes = models.JSONField('notes',blank=True, default=emptyjson)
    observed = models.ForeignKey(Observation,blank=True,null=True,on_delete=models.CASCADE)

    class Meta:
        ordering=["date"]
        get_latest_by = "date"

    def parse_gcn(self):
        import request
        return 'ok'

    def quick(self):
        '''quicklook links/graphs'''
        year=self.date.year
        dayfrac=(self.date.hour+(self.date.minute+self.date.second/60)/60)/24
        qlid=self.date.strftime("%y%m%d")+("%.03f"%dayfrac)[2:]
        #qlid="220815608"
        return f"https://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/triggers/{year}/bn{qlid}/quicklook/glg_lc_medres34_bn{qlid}.gif"
        
    def get_pos(self,shift=0):
        if self.observed:
            dis=self.date-self.observed.dfrom
            return dis.seconds
        return 0

class GCN(models.Model):
    type_choices=[
        ('NO','Notice'),
        ('CC','Circular'),
        ('OR','Other'),
        ('GN','GCN'),
    ]
    gid=models.IntegerField()
    gtype=models.CharField(max_length=2,choices=type_choices,default='GN')
    date = models.DateTimeField('issued')
    related = models.ForeignKey(Observation,blank=True,null=True,on_delete=models.CASCADE)
    brief = models.SlugField(max_length=100,blank=True,null=True)
    class Meta:
        ordering=["gid"]
        get_latest_by = "date"
    def __repr__(self):
        return 'GCN'+str(self.gid)

    def link(self):
        return 'https://gcn.gsfc.nasa.gov/gcn/gcn3/%i.gcn3'%self.gid

    def parse(self,trigtime=False):
        import requests
        lines=requests.get(self.link()).text.split('\n')
        parpos=[]
        from datetime import datetime,timezone
        for i,d3 in enumerate(lines):
            if len(d3)==0:
                parpos.append(i)
            if d3[:4]=='DATE':
                dtstring='20'+d3[d3.find(':')+1:].strip().replace('/','-')[:-4]
                self.date=datetime.fromisoformat(dtstring.replace(' ','T')).replace(tzinfo=timezone.utc)
            elif d3[:4]=='SUBJ':
                self.brief=d3[d3.find(':')+1:].strip()
        if trigtime:
            full=' '.join(lines[parpos[1]+1:]).replace('  ',' ')
            pos1=full.find('peak time')
            if pos1>0:
                dtstring=full[pos1+10:pos1+30].replace('.','')
                print('found trig '+dtstring)
                self.date=datetime.fromisoformat(dtstring.replace(' ','T')).replace(tzinfo=timezone.utc)
        self.save()
        
    def find_obs(self):
        lset=Observation.objects.filter(dfrom__lte=self.date).filter(dto__gte=self.date)
        if len(lset)>0:
            print('found %i observ.'%len(lset))
            self.related=lset[0]
            self.save()
