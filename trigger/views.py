from django.shortcuts import render

from django.http import HttpResponse
from django.views import generic

from .models import *

def index(request):
    return HttpResponse("Hello, world. You're at trigger index. Please have a look at <a href=\"month/9/\">last month</a> GCNs")

# Create your views here.
#class ObserView(generic.ObservationView):
#    model = Observation
#    template_name = 'trigger/observe.html'
from django.http import HttpResponse

def obslist(request):
    context={"olist":Observation.objects.filter(nspec__gt=0).order_by('dto')}
    return render(request, 'trigger/obslist.html', context)

def observe(request, pk):
    context={"obs":Observation.objects.get(pk=pk)}
    return render(request, 'trigger/observe.html', context)

def fermonth(request, fmon, fyear=2022):
    mon="%i-%02i"%(fyear,fmon)
    select=Fermi.objects.filter(date__year=fyear).filter(date__month=fmon)
    #.filter(date__gte=mon+"-01").filter(date__lte=mon+"-30")
    context={'selection': select.order_by('date'),'month':mon}
    context['prev']="%i-%02i"%(fyear,fmon-1) if fmon>1 else "%i-%02i"%(fyear-1,12)
    context['pdat']=[fyear,fmon-1] if fmon>1 else [fyear-1,12]
    context['ndat']=[fyear,fmon+1] if fmon<12 else [fyear+1,1]
    return render(request, 'trigger/fermi.html', context)

def data(request, pk):
    obs=Observation.objects.get(pk=pk)
    context={"obs":obs}
    curve=obs.get_data()
    sel=obs.times>0
    if "start" in request.GET: sel*=obs.times>=float(request.GET["start"])
    if "end" in request.GET: sel*=obs.times<=float(request.GET["end"])
    context["times"]=obs.times[sel]
    context["spec"]=curve[sel]
    if 'col' in request.GET:
        colsel=[int(a)-1 for a in request.GET.getlist('col')]
        context["spec"]=context["spec"][:,colsel]
        fmt="%.4f"+"\t%.3f"*len(colsel)
    else:
        fmt="%.4f"+"\t%.3f"*len(curve[0])
    out=[fmt%tuple([context["times"][i]]+list(sp)) for i,sp in enumerate(context["spec"])]
    return HttpResponse('\n'.join(out), content_type="text/plain")
    #return render(request, 'trigger/curve.txt', context)

def plot(request, pk, bid=4):
    obs=Observation.objects.get(pk=pk)
    context={"obs":obs}
    query=''
    if "start" in request.GET: 
        context['from']=request.GET["start"]
        query+='start='+request.GET["start"]
    if "end" in request.GET: 
        context['to']=request.GET["end"]
        query+='&end='+request.GET["end"]
    if "cent" in request.GET:
        cent=int(request.GET["cent"])
        context['from']=cent-100 if cent>100 else 0
        context['to']=cent+200
        
    from plotly.offline import plot
    import plotly.graph_objects as go
    y2=obs.get_data()[:,bid]
    x=obs.times
    #fig.add_annotation( text="below target!", x=100, y=400, arrowhead=1, showarrow=True )
    if ('dual' in request.GET):
        graphs=[go.Scatter(x=x, y=obs.spec[:,i]+obs.spec[:,i+1], mode='lines', opacity=0.8, name='band %i+%i'%(i,i+1)) for i in range(bid,len(obs.spec[0]),2)]
    else:
        graphs=[go.Scatter(x=x, y=obs.spec[:,i], mode='lines', opacity=0.8, name='band %i'%i) for i in range(bid,len(obs.spec[0]))]
    if "cent" in request.GET:
        graphs.append(go.add_vline(x=cent, line_width=3, line_dash="dash", line_color="green"))
    layout = {
        'title': obs.desc,
        'xaxis_title': 'time from start [s]',
        'yaxis_title': 'rate',
        'height': 420, 'width': 1160,
    }
    if ('log' in request.GET): layout['yaxis_type']='log'
    if 'from' in context: 
        layout['xaxis']={'range':[context['from'],context['to']]}
    context['plot_div']=plot({'data': graphs, 'layout': layout}, output_type='div')
    #map: Scattergeo (or fig.add_scattergeo)
    return render(request, 'trigger/plot1.html', context)

def plot_old(request, pk):
    obs=Observation.objects.get(pk=pk)
    context={"obs":obs}
    context['bands']=[4,6]
    context['camps']=[o.id for o in Observation.objects.all()]
    #['Band%i'%b for b in [4,6]]
    if query!='': context['query']='?'+query+'&col=4&col=6'
    context['staturl']='http://cthulhu.physics.muni.cz:5000/'#"https://physics.muni.cz/~munz/static/"
    return render(request, 'trigger/plot2.html', context)
