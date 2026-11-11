from django import forms
from django.contrib.auth.forms import UserCreationForm


class SignUpForm(UserCreationForm):
    pass


class UploadForm(forms.Form):
    file = forms.FileField()


class AskForm(forms.Form):
    question = forms.CharField(
        max_length=2000, widget=forms.TextInput(attrs={"placeholder": "Ask a question"})
    )
