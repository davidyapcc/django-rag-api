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
    # Set by "Ask a follow-up": the Query this one follows.
    predecessor = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
