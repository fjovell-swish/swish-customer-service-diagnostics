"""
Personal access tokens for the MCP API: MCP clients (Claude Code, Claude Desktop) can't sign in
through the app's browser sign-in, so each person creates a token at /tokens/ and the client
sends it as `Authorization: Bearer <token>`.

Only a hash is stored; the token itself is shown once, when it's created. A token acts as its
person with the roles they had when they last signed in to the app (their role groups).
"""

import hashlib
import secrets
from datetime import datetime
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

PREFIX = "swd_"
# Enough to identify a token in the list without making it guessable.
VISIBLE_CHARS = len(PREFIX) + 4
LIFETIME = timedelta(days=90)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PersonalToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="personal_tokens"
    )
    name = models.CharField(max_length=100, help_text="Where it's used, e.g. “Claude Code”.")
    key_hash = models.CharField(max_length=64, unique=True)
    key_start = models.CharField(max_length=VISIBLE_CHARS)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.key_start}…)"

    @classmethod
    def create(cls, user: User, name: str, now: datetime) -> tuple[PersonalToken, str]:
        """A new token and its value, which is never stored: show it now or never."""
        token = PREFIX + secrets.token_urlsafe(32)
        personal_token = cls.objects.create(
            user=user,
            name=name,
            key_hash=digest(token),
            key_start=token[:VISIBLE_CHARS],
            expires_at=now + LIFETIME,
        )
        return personal_token, token

    @classmethod
    def authenticate(cls, token: str) -> User | None:
        """The active user a valid, unexpired token belongs to; records the use."""
        now = timezone.now()
        personal_token = (
            cls.objects.select_related("user")
            .filter(key_hash=digest(token), expires_at__gt=now, user__is_active=True)
            .first()
        )
        if personal_token is None:
            return None
        cls.objects.filter(pk=personal_token.pk).update(last_used_at=now)
        return personal_token.user

    @property
    def expired(self) -> bool:
        return self.expires_at <= timezone.now()
