from django.shortcuts import render
from django.contrib import messages

def home(request):
    return render(request, 'home.html')

def contacto(request):
    return render(request, 'contacto.html')