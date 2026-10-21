from django.contrib import admin
from django.urls import include, path
from . import views 

urlpatterns = [
    path('', views.index, name='index'),
    path('obs/', views.obslist, name='obslist'),
    path('obs/<int:pk>/', views.observe, name='observe'),
    path('data/<int:pk>/', views.data, name='data'),
    path('plot/<int:pk>/', views.plot, name='plot'),
    #path('obs/<int:pk>/', views.ObserView.as_view(), name='observe'),
    path('year/<int:fyear>/<int:fmon>/', views.fermonth, name='ymonth'),
    path('month/<int:fmon>/', views.fermonth, name='month')
    #path('polls/', include(polls.urls')),
    #path('admin/', admin.site.urls),
]
