"""
Forms — the trust boundary for user input (ARCHITECTURE.md).

Every posted value reaches a service through a form, so this is where Odoo's "validate
user input robustly" requirement is satisfied rather than in scattered view code.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from core.models import Role, User


class SignupForm(UserCreationForm):
    """Self-service signup. **Creates a Sales Rep and nothing else.**

    `role` is deliberately absent from `Meta.fields`, so Django never binds it from POST
    data — a crafted request carrying `role=MANAGER` has nowhere to land. `save()` then
    sets the role explicitly rather than relying on the model default, so the guarantee
    does not quietly depend on a default somebody could change later.

    See ADR-012. The short version: the problem statement asks for signup but never says
    users pick their own role, and a visitor who could grant themselves approval rights
    would defeat the premise of a product whose entire thesis is that discounts are
    governed by someone other than the person giving them.
    """

    name = forms.CharField(
        max_length=150,
        label="Full name",
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "name")  # role is NOT here, on purpose.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field_classes = (
            "mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 "
            "text-slate-100"
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = field_classes

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # Explicit, not inherited from the model default. Signup grants the lowest
        # privilege in the system and only an admin can raise it (ADR-012).
        user.role = Role.REP
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user
