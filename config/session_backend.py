"""Database sessions with independently updated portfolio analysis preferences."""

from asgiref.sync import sync_to_async
from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore
from django.db import connections, router, transaction
from django.utils import timezone

ANALYSIS_DATES_KEY = "portfolio_analysis_dates"


class SessionStore(DatabaseSessionStore):
    def _locked_row(self, using):
        return (
            self.model.objects.using(using)
            .select_for_update()
            .filter(session_key=self.session_key)
            .first()
        )

    def _preserve_analysis_dates(self, row):
        if row is None:
            return
        stored = self.decode(row.session_data)
        if ANALYSIS_DATES_KEY in stored:
            self._session[ANALYSIS_DATES_KEY] = stored[ANALYSIS_DATES_KEY]
        else:
            self._session.pop(ANALYSIS_DATES_KEY, None)

    def save(self, must_create=False):
        using = router.db_for_write(self.model)
        if must_create or self.session_key is None or connections[using].vendor != "postgresql":
            return super().save(must_create=must_create)
        with transaction.atomic(using=using):
            # Middleware can save a request-local snapshot long after another POST.
            self._preserve_analysis_dates(self._locked_row(using))
            return super().save(must_create=must_create)

    async def asave(self, must_create=False):
        return await sync_to_async(self.save)(must_create=must_create)

    def cycle_key(self):
        using = router.db_for_write(self.model)
        if self.session_key is None or connections[using].vendor != "postgresql":
            return super().cycle_key()
        with transaction.atomic(using=using):
            self._preserve_analysis_dates(self._locked_row(using))
            return super().cycle_key()

    async def acycle_key(self):
        return await sync_to_async(self.cycle_key)()

    def update_analysis_dates(self, update):
        using = router.db_for_write(self.model)
        with transaction.atomic(using=using):
            row = self._locked_row(using)
            if row is None or row.expire_date <= timezone.now():
                return
            data = self.decode(row.session_data)
            current = data.get(ANALYSIS_DATES_KEY)
            updated = update(current if isinstance(current, dict) else {})
            if updated != current:
                data[ANALYSIS_DATES_KEY] = updated
                row.session_data = self.encode(data)
                row.save(using=using, update_fields=["session_data"])
