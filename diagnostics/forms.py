from typing import Any

from django import forms
from django.conf import settings

from diagnostics.models import Case
from diagnostics.workflow import Question

FREE_TEXT_MAX_LENGTH = 200


class StartForm(forms.ModelForm[Case]):
    class Meta:
        model = Case
        fields = ["identity", "tenant", "ticket"]
        widgets = {"identity": forms.HiddenInput, "tenant": forms.HiddenInput}

    def clean_tenant(self) -> str:
        tenant: str = self.cleaned_data["tenant"]
        if tenant not in settings.OCPP_TENANTS:
            raise forms.ValidationError("Unknown tenant.")
        return tenant


class AnswerForm(forms.Form):
    """One question: radio buttons for its choices, or a free-text box that may stay empty."""

    def __init__(self, question: Question, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if question.choices:
            self.fields["answer"] = forms.ChoiceField(
                label=question.text,
                help_text=question.help,
                choices=question.choices,
                widget=forms.RadioSelect,
            )
        else:
            self.fields["answer"] = forms.CharField(
                label=question.text,
                help_text=question.help,
                required=False,
                max_length=FREE_TEXT_MAX_LENGTH,
            )
