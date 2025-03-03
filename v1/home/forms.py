from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm



class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user

from .models import XTBConnection

class XTBConnectionForm(forms.ModelForm):
    # Ręcznie definiujemy pole dla hasła jako tekstowe (PasswordInput)
    password = forms.CharField(widget=forms.PasswordInput, label="Password")

    class Meta:
        model = XTBConnection
        fields = ['xtb_id']  

    def save(self, commit=True):
        # Przechwycenie zapisu, aby obsłużyć szyfrowanie hasła
        instance = super().save(commit=False)
        instance.set_password(self.cleaned_data['password'])  # Hashowanie hasła
        if commit:
            instance.save()
        return instance

# bots/forms.py
from django import forms
from .models import Bot

class BotForm(forms.ModelForm):
    class Meta:
        model = Bot
        fields = [
            'name', 'instrument',
            'max_price',
            'percent', 'capital',
            'stream_session_id'
        ]

#---------------------------------------------------------#

class BinanceApiForm(forms.ModelForm):
    binance_api_secret = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••'}),
        required=False,
        help_text="Leave empty to keep your existing secret"
    )
    
    class Meta:
        model = UserProfile
        fields = ['binance_api_key']
        widgets = {
            'binance_api_key': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Get the plaintext secret from the form
        binance_api_secret = self.cleaned_data.get('binance_api_secret')
        
        # Only update the secret if one was provided
        if binance_api_secret:
            instance.set_binance_api_secret(binance_api_secret)
            
        if commit:
            instance.save()
        
        return instance