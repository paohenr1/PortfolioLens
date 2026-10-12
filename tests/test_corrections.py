"""Independent correction arithmetic, private signed previews and database integrity."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from ledger.analytics import positions_snapshot
from ledger.correction_forms import ReplacementForm, SaveCorrectionForm, VoidForm
from ledger.correction_views import PREVIEW_SALT
from ledger.corrections import (
    checked_preview,
    commit_correction,
    preview_correction,
    validate_reason,
)
from ledger.domain import LedgerRuleError
from ledger.journal import effective_entries
from ledger.models import Correction, Entry
from ledger.performance import build_plan
from ledger.performance_services import load_performance
from ledger.services import PortfolioUnavailable, append_entry
from market_data.errors import CredentialsMissing, ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade

D = Decimal
REASON = "Correct transcription from the execution record"


class CorrectionFormTests(SimpleTestCase):
    def test_reason_is_required_bounded_control_free_and_trimmed(self):
        for value in ("", "   ", "x" * 501, "Unsafe\nreason", "Unsafe\x7freason", None):
            with self.assertRaises(LedgerRuleError):
                validate_reason(value)
        self.assertEqual(validate_reason("  Fixed fixture  "), "Fixed fixture")

    def test_void_requires_reason_key_and_save_requires_review_confirmation(self):
        self.assertTrue(VoidForm({"reason": REASON, "client_key": uuid.uuid4()}).is_valid())
        self.assertFalse(VoidForm({"reason": REASON}).is_valid())
        self.assertFalse(SaveCorrectionForm({"preview_token": "signed-fixture"}).is_valid())
        self.assertFalse(
            SaveCorrectionForm({"preview_token": "x" * 8193, "confirmed": "on"}).is_valid()
        )

    def test_replacement_initial_values_preserve_original_date_kind_and_order(self):
        form = ReplacementForm(initial=asdict(trade(kind="SELL", sequence=7)))
        self.assertEqual(form.initial["kind"], "SELL")
        self.assertEqual(form.initial["event_date"], DAY)
        self.assertEqual(form.initial["sequence"], 7)


@skipUnless(connection.vendor == "postgresql", "Corrections require PostgreSQL")
class CorrectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("correction-owner")
        cls.other = get_user_model().objects.create_user("correction-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Correction fixture")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign correction secret")

    def setUp(self):
        self.client.force_login(self.owner)
        self.provider = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)
        self.deposit = self.record(cash())

    def record(self, intent, **extra):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
            **extra,
        )

    def preview(self, target=None, intent=None):
        return preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=(target or self.deposit).pk,
            intent=intent,
            reason=REASON,
        )

    def commit(self, target=None, intent=None, key=None, version=None, reason=REASON):
        target = target or self.deposit
        if version is None:
            version = self.preview(target, intent)[4]
        return commit_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=target.pk,
            intent=intent,
            reason=reason,
            client_key=key or uuid.uuid4(),
            expected_version=version,
            client_address="127.0.0.1",
        )

    def url(self, name="ledger_correct", target=None, portfolio=None):
        args = [(portfolio or self.portfolio).pk]
        if name in ("ledger_correct", "ledger_void"):
            args.append((target or self.deposit).pk)
        return reverse(name, args=args)

    def data(self, intent=None, **changes):
        values = {
            key: str(value) if value is not None else ""
            for key, value in asdict(intent or cash(amount=D("1100"))).items()
        }
        return {**values, "client_key": str(uuid.uuid4()), "reason": REASON, **changes}

    def http_preview(self, intent=None, target=None, void=False):
        response = self.client.post(
            self.url("ledger_void" if void else "ledger_correct", target), self.data(intent)
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        token = response.context["save_form"].initial["preview_token"]
        return response, {"stage": "save", "preview_token": token, "confirmed": "on"}

    def test_replace_same_order_preserves_original_and_restates_cash(self):
        before = Entry.objects.values().get(pk=self.deposit.pk)
        correction = self.commit(intent=cash(amount=D("1200")))
        self.assertEqual(Entry.objects.values().get(pk=self.deposit.pk), before)
        self.assertEqual(correction.replacement.revision, 1)
        self.assertTrue(correction.replacement.is_replacement)
        self.assertEqual(list(effective_entries(self.portfolio)), [correction.replacement])
        self.assertEqual(positions_snapshot(self.owner, self.portfolio.pk)[1].cash, D("1200"))
        self.provider.assert_not_called()

    def test_void_fee_preserves_original_and_has_no_provider_request(self):
        fee = self.record(cash(kind="FEE", amount=D("10"), sequence=2))
        correction = self.commit(fee)
        self.assertIsNone(correction.replacement)
        self.assertEqual(Entry.objects.count(), 2)
        self.assertEqual(positions_snapshot(self.owner, self.portfolio.pk)[1].cash, D("1000"))
        self.provider.assert_not_called()

    def test_funded_deposit_void_is_rejected_before_any_write(self):
        self.record(trade())
        self.provider.reset_mock()
        with self.assertRaisesMessage(LedgerRuleError, "cash negative"):
            self.preview()
        self.assertEqual(Correction.objects.count(), 0)
        self.assertEqual(Entry.objects.count(), 2)
        self.provider.assert_not_called()

    def test_buy_quantity_reduction_checks_later_sale_prefix(self):
        buy = self.record(trade())
        self.record(trade(kind="SELL", quantity=D("6"), sequence=3))
        self.provider.reset_mock()
        with self.assertRaisesMessage(LedgerRuleError, "short position"):
            self.preview(buy, trade(quantity=D("5")))
        self.assertEqual(Correction.objects.count(), 0)
        self.provider.assert_not_called()

    def test_changed_buy_recomputes_sale_basis_gain_and_remaining_lots(self):
        buy = self.record(trade())
        self.record(trade(kind="SELL", quantity=D("4"), price=D("30"), fees=D("2"), sequence=3))
        self.provider.reset_mock()
        self.commit(buy, trade(price=D("20")))
        result = positions_snapshot(self.owner, self.portfolio.pk)[1]
        self.assertEqual(result.cash, D("917.00"))
        self.assertEqual(result.realized_gain, D("37.60"))
        self.assertEqual(result.open_cost_basis, D("120.60"))
        self.assertEqual(result.positions[0].quantity, D("6"))
        self.provider.assert_called_once()

    def test_date_change_cannot_move_funding_after_purchase(self):
        self.record(trade())
        with self.assertRaisesMessage(LedgerRuleError, "cash negative"):
            self.preview(intent=cash(event_date=date(2020, 1, 3)))

    def test_split_exactness_is_rechecked_against_corrected_lot(self):
        buy = self.record(trade(quantity=D("3")))
        split = replace(
            cash(sequence=3),
            kind="SPLIT",
            amount=None,
            security_id=REFERENCE.security.id,
            split_new=1,
            split_old=3,
        )
        self.record(split)
        self.provider.reset_mock()
        with self.assertRaisesMessage(LedgerRuleError, "cannot preserve"):
            self.preview(buy, trade(quantity=D("1")))
        self.provider.assert_not_called()

    def test_voiding_buy_keeps_received_dividend_without_inventing_ownership(self):
        buy = self.record(trade())
        self.record(
            replace(
                cash(sequence=3, amount=D("5")), kind="DIVIDEND", security_id=REFERENCE.security.id
            )
        )
        self.commit(buy)
        result = positions_snapshot(self.owner, self.portfolio.pk)[1]
        self.assertEqual(result.cash, D("1005"))
        self.assertEqual(result.net_dividends, D("5"))
        self.assertEqual(result.positions, ())

    def test_external_flow_plan_uses_replacement_not_original_or_audit_marker(self):
        flow = self.record(cash(amount=D("100"), event_date=date(2020, 1, 3), sequence=1))
        self.commit(flow, cash(amount=D("200"), event_date=date(2020, 1, 3), sequence=1))
        entries = list(effective_entries(self.portfolio))
        boundaries = build_plan([entry.as_input() for entry in entries], DAY, date(2020, 1, 4))
        self.assertEqual(boundaries[1].external_flow, D("200"))
        _, performance, values, error = load_performance(
            self.owner, self.portfolio.pk, DAY, date(2020, 1, 4), "127.0.0.1"
        )
        self.assertEqual(performance.return_percent, D("0.0000"))
        self.assertEqual(values[-1].cash, D("1200"))
        self.assertIsNone(error)
        self.provider.assert_not_called()

    def test_historical_positions_use_corrected_event_date(self):
        self.commit(intent=cash(amount=D("1200"), event_date=date(2020, 1, 3)))
        self.assertEqual(
            positions_snapshot(self.owner, self.portfolio.pk, as_of=DAY)[1].cash, D("0")
        )
        self.assertEqual(
            positions_snapshot(self.owner, self.portfolio.pk, as_of=date(2020, 1, 3))[1].cash,
            D("1200"),
        )

    def test_preview_is_read_only_and_reports_hand_checked_effect(self):
        response, _ = self.http_preview()
        self.assertEqual(response.context["before"].cash, D("1000"))
        self.assertEqual(response.context["after"].cash, D("1100"))
        self.assertContains(response, "Correction preview")
        self.assertContains(response, "No open positions")
        self.assertEqual(Correction.objects.count(), 0)
        self.assertEqual(Entry.objects.count(), 1)
        self.provider.assert_not_called()

    def test_signed_preview_saves_once_and_ignores_unsigned_new_values(self):
        _, data = self.http_preview()
        data["amount"] = "999999"
        for _ in range(2):
            response = self.client.post(self.url(), data)
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Correction.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 2)
        self.assertEqual(Correction.objects.get().replacement.amount, D("1100"))
        self.provider.assert_not_called()

    def test_save_without_confirmation_retains_valid_preview_without_write(self):
        _, data = self.http_preview()
        data.pop("confirmed")
        response = self.client.post(self.url(), data)
        self.assertContains(response, "Correction preview", status_code=400)
        self.assertEqual(response.context["after"].cash, D("1100"))
        self.assertEqual(Correction.objects.count(), 0)

    def test_tampered_expired_oversized_or_wrong_mode_token_is_rejected(self):
        _, data = self.http_preview()
        for token in ("invalid-fixture", data["preview_token"] + "x", "x" * 8193):
            response = self.client.post(self.url(), {**data, "preview_token": token})
            self.assertEqual(response.status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + 901):
            response = self.client.post(self.url(), data)
            self.assertContains(response, "invalid or expired", status_code=400)
        response = self.client.post(self.url("ledger_void"), data)
        self.assertContains(response, "invalid or expired", status_code=400)
        self.assertEqual(Correction.objects.count(), 0)
        self.provider.assert_not_called()

    def test_signed_token_is_bound_to_owner_portfolio_and_target(self):
        _, data = self.http_preview()
        payload = signing.loads(data["preview_token"], salt=PREVIEW_SALT)
        for field, value in (
            ("owner", str(self.other.pk)),
            ("portfolio", str(self.foreign.pk)),
            ("target", str(uuid.uuid4())),
        ):
            token = signing.dumps({**payload, field: value}, salt=PREVIEW_SALT)
            self.assertEqual(
                self.client.post(self.url(), {**data, "preview_token": token}).status_code, 400
            )
        self.assertEqual(Correction.objects.count(), 0)

    def test_stale_preview_rejects_before_provider_and_repreview_can_succeed(self):
        _, data = self.http_preview()
        self.record(cash(sequence=2, amount=D("10")))
        response = self.client.post(self.url(), data)
        self.assertContains(response, "journal changed", status_code=400)
        self.assertEqual(Correction.objects.count(), 0)
        _, data = self.http_preview()
        self.assertEqual(self.client.post(self.url(), data).status_code, 302)
        self.provider.assert_not_called()

    def test_provider_failure_creates_neither_replacement_nor_correction(self):
        buy = self.record(trade())
        _, data = self.http_preview(trade(price=D("20")), buy)
        for error in (CredentialsMissing(), ProviderRateLimited(42)):
            self.provider.side_effect = error
            response = self.client.post(self.url(target=buy), data)
            self.assertEqual(response.status_code, error.status)
            if error.retry_after:
                self.assertEqual(response.headers["Retry-After"], "42")
            self.assertEqual(Correction.objects.count(), 0)
            self.assertEqual(Entry.objects.count(), 2)

    def test_reference_failure_and_venue_change_cannot_save(self):
        buy = self.record(trade())
        self.record(trade(kind="SELL", sequence=3, quantity=D("1")))
        self.provider.return_value = replace(
            REFERENCE, security=replace(REFERENCE.security, exchange_mic="XNAS")
        )
        with self.assertRaisesMessage(LedgerRuleError, "venue changed"):
            self.commit(buy, trade(price=D("20")))
        self.assertEqual(Correction.objects.count(), 0)
        self.assertEqual(Entry.objects.count(), 3)

    def test_exact_service_retry_uses_no_reference_and_changed_reason_is_rejected(self):
        buy = self.record(trade())
        intent, key = trade(price=D("20")), uuid.uuid4()
        first = self.commit(buy, intent, key=key)
        self.provider.reset_mock()
        result = self.commit(buy, intent, key=key, version="old-signed-version")
        self.assertEqual(result.pk, first.pk)
        with self.assertRaisesMessage(LedgerRuleError, "different correction details"):
            self.commit(buy, intent, key=key, version="old", reason="Different reason")
        self.provider.assert_not_called()

    def test_append_and_correction_submission_keys_cannot_be_cross_reused(self):
        with self.assertRaisesMessage(LedgerRuleError, "belongs to a transaction"):
            self.commit(intent=cash(amount=D("1200")), key=self.deposit.client_key)
        correction = self.commit(intent=cash(amount=D("1200")))
        with self.assertRaisesMessage(ValidationError, "belongs to a correction"):
            append_entry(
                user=self.owner,
                portfolio_id=self.portfolio.pk,
                client_key=correction.client_key,
                intent=cash(sequence=2),
                client_address="127.0.0.1",
            )

    def test_correct_current_replacement_and_reject_already_corrected_original(self):
        first = self.commit(intent=cash(amount=D("1200")))
        second = self.commit(first.replacement, cash(amount=D("1300")))
        self.assertEqual(second.replacement.revision, 2)
        self.assertEqual(list(effective_entries(self.portfolio)), [second.replacement])
        self.assertEqual(Correction.objects.count(), 2)
        with self.assertRaisesMessage(LedgerRuleError, "already been corrected"):
            self.preview(intent=cash(amount=D("1400")))

    def test_voided_order_can_be_reused_by_normal_append_without_resurrection(self):
        self.commit()
        new = self.record(cash(amount=D("500")))
        self.assertEqual(new.revision, 1)
        self.assertFalse(new.is_replacement)
        self.assertEqual(list(effective_entries(self.portfolio)), [new])

    def test_identical_replacement_and_active_duplicate_order_are_rejected(self):
        with self.assertRaisesMessage(LedgerRuleError, "must change"):
            self.preview(intent=cash())
        self.record(cash(sequence=2))
        with self.assertRaisesMessage(LedgerRuleError, "order is already used"):
            self.preview(intent=cash(sequence=2, amount=D("200")))

    def test_capacity_counts_all_versions_and_allows_void_at_entry_limit(self):
        with patch("ledger.corrections.MAX_ENTRIES_PER_PORTFOLIO", 1):
            with self.assertRaisesMessage(LedgerRuleError, "entry development limit"):
                self.preview(intent=cash(amount=D("1200")))
            self.commit()
        with patch("ledger.services.MAX_ENTRIES_PER_PORTFOLIO", 1):
            with self.assertRaisesMessage(ValidationError, "development limit"):
                self.record(cash(amount=D("100")))

    def test_correction_allowance_rejects_before_provider(self):
        with patch("ledger.corrections.MAX_CORRECTIONS_PER_PORTFOLIO", 0):
            with self.assertRaisesMessage(LedgerRuleError, "correction development limit"):
                self.preview()
        self.provider.assert_not_called()

    def test_foreign_portfolio_entry_and_signed_out_access_are_private(self):
        for name in ("ledger_correct", "ledger_void", "ledger_audit"):
            response = self.client.get(self.url(name, portfolio=self.foreign))
            self.assertEqual(response.status_code, 404)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertNotIn(self.foreign.name, response.content.decode())
            if name != "ledger_audit":
                self.assertEqual(
                    self.client.post(
                        self.url(name, portfolio=self.foreign), self.data()
                    ).status_code,
                    404,
                )
        with self.assertRaises(PortfolioUnavailable):
            preview_correction(
                user=self.other,
                portfolio_id=self.portfolio.pk,
                target_id=self.deposit.pk,
                intent=None,
                reason=REASON,
            )
        self.client.logout()
        for name in ("ledger_correct", "ledger_void", "ledger_audit"):
            self.assertEqual(self.client.get(self.url(name)).status_code, 302)
        self.provider.assert_not_called()

    def test_csrf_methods_and_get_are_safe(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        _, data = self.http_preview()
        self.assertEqual(csrf.post(self.url(), data).status_code, 403)
        csrf.get(self.url())
        data["csrfmiddlewaretoken"] = csrf.cookies["csrftoken"].value
        self.assertEqual(csrf.post(self.url(), data).status_code, 302)
        for name in ("ledger_correct", "ledger_void", "ledger_audit"):
            response = self.client.put(self.url(name))
            self.assertEqual(response.status_code, 405)
            self.assertIn("no-store", response.headers["Cache-Control"])

    def test_audit_escapes_reason_and_shows_full_original_and_replacement(self):
        self.commit(intent=cash(amount=D("1200")), reason="<script>fixture reason</script>")
        response = self.client.get(self.url("ledger_audit"))
        self.assertContains(response, "Original entry")
        self.assertContains(response, "Replacement entry")
        self.assertContains(response, str(self.deposit.pk))
        self.assertContains(response, "&lt;script&gt;fixture reason&lt;/script&gt;")
        self.assertNotContains(response, "<script>fixture reason</script>")
        self.assertContains(response, "1000.00")
        self.assertContains(response, "1200.00")

    def test_model_and_database_block_audit_updates_deletes(self):
        correction = self.commit()
        with self.assertRaises(ValidationError):
            correction.save()
        with self.assertRaises(ValidationError):
            correction.delete()
        for action in (
            lambda: Correction.objects.filter(pk=correction.pk).update(reason="changed"),
            lambda: Correction.objects.filter(pk=correction.pk).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                action()

    def test_database_blocks_foreign_target_and_unflagged_replacement(self):
        other_entry = append_entry(
            user=self.other,
            portfolio_id=self.foreign.pk,
            client_key=uuid.uuid4(),
            intent=cash(),
            client_address="127.0.0.1",
        )
        for target, replacement in (
            (other_entry, None),
            (self.deposit, other_entry),
            (self.deposit, self.deposit),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Correction.objects.create(
                    portfolio=self.portfolio,
                    target=target,
                    replacement=replacement,
                    reason=REASON,
                    client_key=uuid.uuid4(),
                )

    def test_database_blocks_orphan_replacement_and_duplicate_effective_order(self):
        for values in ({"is_replacement": True, "sequence": 2}, {"revision": 1}):
            with (
                self.subTest(values=values),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                Entry.objects.create(
                    portfolio=self.portfolio,
                    client_key=uuid.uuid4(),
                    kind="DEPOSIT",
                    event_date=DAY,
                    sequence=values.get("sequence", 1),
                    amount=D("10"),
                    **{k: v for k, v in values.items() if k != "sequence"},
                )
                connection.check_constraints()

    def test_identical_commit_during_preflight_recovers_its_retry_result(self):
        key, intent = uuid.uuid4(), cash(amount=D("1200"))
        version = self.preview(intent=intent)[4]
        completed = False

        def concurrent(*args):
            nonlocal completed
            if not completed:
                completed = True
                self.commit(intent=intent, key=key, version=version)
            return checked_preview(*args)

        with patch("ledger.corrections.checked_preview", side_effect=concurrent):
            result = self.commit(intent=intent, key=key, version=version)
        self.assertEqual(result.pk, Correction.objects.get().pk)
        self.assertEqual(Entry.objects.count(), 2)

    def test_failed_audit_insertion_rolls_back_the_replacement(self):
        with patch("ledger.models.Correction.save", side_effect=ValidationError("Fixture failure")):
            with self.assertRaises(ValidationError):
                self.commit(intent=cash(amount=D("1200")))
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Correction.objects.count(), 0)
        self.assertEqual(list(effective_entries(self.portfolio)), [self.deposit])

    def test_audit_pagination_keeps_all_decisions_without_provider_calls(self):
        entries = [self.deposit] + [
            self.record(cash(sequence=n, amount=D("10"))) for n in range(2, 22)
        ]
        for entry in entries:
            self.commit(entry)
        first = self.client.get(self.url("ledger_audit"))
        second = self.client.get(self.url("ledger_audit"), {"page": 2})
        self.assertEqual(len(first.context["page"]), 20)
        self.assertEqual(len(second.context["page"]), 1)
        self.assertEqual(Entry.objects.count(), 21)
        self.provider.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Concurrency requires PostgreSQL")
class CorrectionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("correction-race-owner")
        self.portfolio = create_portfolio(owner=self.owner, name="Correction race")
        self.deposit = append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=cash(),
            client_address="127.0.0.1",
        )
        self.version = preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=self.deposit.pk,
            intent=cash(amount=D("1200")),
            reason=REASON,
        )[4]

    def correct(self, key):
        return commit_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=self.deposit.pk,
            intent=cash(amount=D("1200")),
            reason=REASON,
            client_key=key,
            expected_version=self.version,
            client_address="127.0.0.1",
        )

    def race(self, actions):
        barrier = Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return actions[index]()
            except (LedgerRuleError, ValidationError, IntegrityError):
                return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, (0, 1)))

    def test_concurrent_identical_retry_saves_one_replacement_and_audit(self):
        key = uuid.uuid4()
        result = self.race((lambda: self.correct(key), lambda: self.correct(key)))
        self.assertEqual(result[0].pk, result[1].pk)
        self.assertEqual(Correction.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 2)

    def test_competing_corrections_of_same_target_allow_only_one(self):
        result = self.race((lambda: self.correct(uuid.uuid4()), lambda: self.correct(uuid.uuid4())))
        self.assertEqual(sum(item is not None for item in result), 1)
        self.assertEqual(Correction.objects.count(), 1)
        self.assertEqual(len(effective_entries(self.portfolio)), 1)

    def test_append_racing_correction_keeps_valid_final_cash(self):
        result = self.race(
            (
                lambda: self.correct(uuid.uuid4()),
                lambda: append_entry(
                    user=self.owner,
                    portfolio_id=self.portfolio.pk,
                    client_key=uuid.uuid4(),
                    intent=cash(kind="WITHDRAWAL", amount=D("900"), sequence=2),
                    client_address="127.0.0.1",
                ),
            )
        )
        self.assertIsNotNone(result[1])
        analysis = positions_snapshot(self.owner, self.portfolio.pk)[1]
        self.assertIn(analysis.cash, (D("100"), D("300")))

    def test_journal_changed_during_reference_lookup_aborts_correction(self):
        with patch("ledger.services.market_data.security_details", return_value=REFERENCE):
            buy = append_entry(
                user=self.owner,
                portfolio_id=self.portfolio.pk,
                client_key=uuid.uuid4(),
                intent=trade(),
                client_address="127.0.0.1",
            )
        intent = trade(price=D("20"))
        version = preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=buy.pk,
            intent=intent,
            reason=REASON,
        )[4]

        def changed(*args):
            append_entry(
                user=self.owner,
                portfolio_id=self.portfolio.pk,
                client_key=uuid.uuid4(),
                intent=cash(sequence=3, amount=D("5")),
                client_address="127.0.0.1",
            )
            return REFERENCE

        with patch("ledger.services.market_data.security_details", side_effect=changed):
            with self.assertRaisesMessage(LedgerRuleError, "journal changed"):
                commit_correction(
                    user=self.owner,
                    portfolio_id=self.portfolio.pk,
                    target_id=buy.pk,
                    intent=intent,
                    reason=REASON,
                    client_key=uuid.uuid4(),
                    expected_version=version,
                    client_address="127.0.0.1",
                )
        self.assertEqual(Correction.objects.count(), 0)
        self.assertEqual(Entry.objects.count(), 3)

    def test_direct_sql_racing_revisions_cannot_create_duplicate_effective_order(self):
        def raw(index):
            with transaction.atomic():
                return Entry.objects.create(
                    portfolio=self.portfolio,
                    client_key=uuid.uuid4(),
                    kind="DEPOSIT",
                    event_date=DAY,
                    sequence=2,
                    revision=index,
                    amount=D("10"),
                )

        result = self.race((lambda: raw(0), lambda: raw(1)))
        self.assertEqual(sum(item is not None for item in result), 1)
        self.assertEqual(Entry.objects.count(), 2)


@skipUnless(connection.vendor == "postgresql", "Upgrade verification requires PostgreSQL")
class CorrectionMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_original_values_and_immutable_trigger(self):
        executor = MigrationExecutor(connection)
        old = [("ledger", "0003_corporate_actions")]
        latest = executor.loader.graph.leaf_nodes("ledger")
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            owner = apps.get_model("accounts", "User").objects.create(username="correction-upgrade")
            portfolio = apps.get_model("portfolios", "Portfolio").objects.create(
                owner_id=owner.pk, name="Upgrade"
            )
            original = apps.get_model("ledger", "Entry").objects.create(
                portfolio_id=portfolio.pk,
                client_key=uuid.uuid4(),
                kind="DEPOSIT",
                event_date=DAY,
                sequence=1,
                amount=D("123.45"),
            )
            before = apps.get_model("ledger", "Entry").objects.values().get(pk=original.pk)
        finally:
            MigrationExecutor(connection).migrate(latest)
        after = Entry.objects.values().get(pk=original.pk)
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual(after["revision"], 0)
        self.assertFalse(after["is_replacement"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.filter(pk=original.pk).update(amount=D("5"))


class CorrectionStorageGuardTests(TestCase):
    def test_storage_guard_covers_all_correction_routes_without_writes(self):
        owner = get_user_model().objects.create_user("correction-storage")
        self.client.force_login(owner)
        with patch("portfolios.services.connection") as database:
            database.vendor = "sqlite"
            for name in ("ledger_correct", "ledger_void", "ledger_audit"):
                args = [uuid.uuid4()] if name == "ledger_audit" else [uuid.uuid4(), uuid.uuid4()]
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 503)
                self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(Correction.objects.count(), 0)
