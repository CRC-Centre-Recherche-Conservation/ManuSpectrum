from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase

from manuspectrum.models import SiteNotice, format_reminders, parse_reminders
from manuspectrum.models import site_now


def make(**overrides):
    start = site_now() + timedelta(days=2)
    fields = {
        "text_en": "The site will be unavailable.",
        "text_fr": "Le site sera indisponible.",
        "starts_at": start,
        "ends_at": start + timedelta(hours=2),
    }
    fields.update(overrides)
    return SiteNotice(**fields)


class ReminderParsingTests(TestCase):
    def test_sorts_largest_first_and_drops_duplicates(self):
        self.assertEqual(
            parse_reminders("10m, 1h 7d 1d 60m"), [604800, 86400, 3600, 600]
        )

    def test_rejects_a_token_that_is_not_a_duration(self):
        for text in ("7days", "h", "1.5h", "0m", "-1d"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_reminders(text)

    def test_canonical_form_uses_the_largest_exact_unit(self):
        self.assertEqual(
            format_reminders([604800, 90000, 3600, 600, 120]), "7d 25h 1h 10m 2m"
        )

    def test_blank_gives_no_reminder(self):
        self.assertEqual(parse_reminders("  "), [])


class CleanTests(TestCase):
    def test_a_valid_notice_passes_and_reminders_are_normalised(self):
        notice = make(reminders="10m,1h 7d 1d")
        notice.full_clean()
        self.assertEqual(notice.reminders, "7d 1d 1h 10m")

    def test_end_must_follow_start(self):
        notice = make()
        notice.ends_at = notice.starts_at
        with self.assertRaises(ValidationError) as caught:
            notice.full_clean()
        self.assertIn("ends_at", caught.exception.message_dict)

    def test_reminders_need_one_valid_duration_within_ninety_days(self):
        for text in ("", "soon", "91d"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    make(reminders=text).full_clean()
                self.assertIn("reminders", caught.exception.message_dict)
        make(reminders="90d").full_clean()

    def test_a_link_needs_both_labels(self):
        with self.assertRaises(ValidationError) as caught:
            make(link_url="https://example.org/", link_label_en="Details").full_clean()
        self.assertEqual(list(caught.exception.message_dict), ["link_label_fr"])
        make(
            link_url="https://example.org/",
            link_label_en="Details",
            link_label_fr="Détails",
        ).full_clean()

    def test_labels_without_a_link_are_accepted(self):
        make().full_clean()


class VersionTests(TestCase):
    def test_version_moves_with_each_save(self):
        notice = make()
        notice.save()
        first = notice.version
        SiteNotice.objects.filter(pk=notice.pk).update(
            updated_at=notice.updated_at - timedelta(minutes=5)
        )
        notice.refresh_from_db()
        self.assertEqual(first - notice.version, 300)

    def test_str_is_the_start_of_the_english_text(self):
        self.assertEqual(str(make(text_en="x" * 100)), "x" * 60)

    def test_reminder_seconds_reads_the_stored_text(self):
        self.assertEqual(make(reminders="1d 1h").reminder_seconds(), [86400, 3600])
        self.assertEqual(make(reminders="oops").reminder_seconds(), [])


class AdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        self.client.force_login(
            User.objects.create_superuser("root-editor", "root@manuspectrum.test", "x")
        )
        self.notice = make()
        self.notice.save()

    def test_changelist_and_change_page_render(self):
        for url in (
            "/en/admin/manuspectrum/sitenotice/",
            f"/en/admin/manuspectrum/sitenotice/{self.notice.pk}/change/",
            "/fr/admin/manuspectrum/sitenotice/add/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_state_follows_the_clock(self):
        from manuspectrum.admin import SiteNoticeAdmin
        from django.contrib import admin

        model_admin = SiteNoticeAdmin(SiteNotice, admin.site)
        now = site_now()
        cases = {
            "scheduled": (now + timedelta(days=30), 2),
            "shown": (now + timedelta(days=3), 2),
            "in progress": (now - timedelta(hours=1), 3),
            "over": (now - timedelta(days=2), 1),
            "unpublished": (now - timedelta(hours=1), 3),
        }
        for expected, (start, hours) in cases.items():
            with self.subTest(expected=expected):
                notice = make(
                    starts_at=start,
                    ends_at=start + timedelta(hours=hours),
                    is_active=expected != "unpublished",
                )
                self.assertEqual(str(model_admin.state(notice)), expected)

    def test_schedule_preview_names_the_moments(self):
        from manuspectrum.admin import SiteNoticeAdmin
        from django.contrib import admin

        start = site_now().replace(hour=8, minute=0, second=0) + timedelta(days=3)
        notice = make(starts_at=start, ends_at=start + timedelta(hours=2))
        text = SiteNoticeAdmin(SiteNotice, admin.site).schedule(notice)
        self.assertIn("Shown from", text)
        self.assertIn("gone at", text)
        self.assertIn("Europe/Paris", text)

    def test_schedule_preview_prints_the_end_day_when_it_differs(self):
        from manuspectrum.admin import SiteNoticeAdmin
        from django.contrib import admin

        start = site_now().replace(hour=22, minute=0, second=0) + timedelta(days=3)
        notice = make(starts_at=start, ends_at=start + timedelta(hours=6))
        text = str(SiteNoticeAdmin(SiteNotice, admin.site).schedule(notice))
        same_day = make(starts_at=start, ends_at=start + timedelta(hours=1))
        short = str(SiteNoticeAdmin(SiteNotice, admin.site).schedule(same_day))
        end_day = (start + timedelta(hours=6)).strftime("%-d")
        self.assertRegex(text, rf"22:00–\w+ {end_day} \w+ 04:00")
        self.assertRegex(short, r"22:00–23:00")

    def test_a_shown_once_notice_needs_no_reminders(self):
        notice = make(display="once", reminders="")
        notice.full_clean()
        self.assertEqual(notice.reminder_seconds(), [])
        with self.assertRaises(ValidationError) as caught:
            make(display="event", reminders="").full_clean()
        self.assertIn("reminders", caught.exception.message_dict)
        with self.assertRaises(ValidationError):
            make(display="other").full_clean()

    def test_shown_once_state_and_schedule_preview(self):
        from manuspectrum.admin import SiteNoticeAdmin
        from django.contrib import admin

        model_admin = SiteNoticeAdmin(SiteNotice, admin.site)
        now = site_now()
        for expected, start in (
            ("scheduled", now + timedelta(days=2)),
            ("shown", now - timedelta(hours=1)),
            ("over", now - timedelta(days=3)),
        ):
            with self.subTest(expected=expected):
                notice = make(
                    display="once",
                    starts_at=start,
                    ends_at=start + timedelta(hours=2 if expected != "over" else 1),
                )
                self.assertEqual(str(model_admin.state(notice)), expected)
        text = str(model_admin.schedule(notice))
        self.assertIn("Shown from", text)
        self.assertIn("until", text)
        self.assertNotIn("reminders", text)
        self.assertNotIn("in progress", text)

    def test_preview_link_points_to_the_homepage_with_the_notice_id(self):
        response = self.client.get(
            f"/en/admin/manuspectrum/sitenotice/{self.notice.pk}/change/"
        )
        self.assertContains(response, f"?ms-notice-preview={self.notice.pk}")

    def test_saving_through_the_form_normalises_reminders(self):
        from manuspectrum.admin import SiteNoticeForm

        start = site_now() + timedelta(days=4)
        form = SiteNoticeForm(
            {
                "kind": "info",
                "display": "event",
                "text_en": "a",
                "text_fr": "b",
                "starts_at_0": start.strftime("%Y-%m-%d"),
                "starts_at_1": start.strftime("%H:%M"),
                "ends_at_0": (start + timedelta(hours=1)).strftime("%Y-%m-%d"),
                "ends_at_1": (start + timedelta(hours=1)).strftime("%H:%M"),
                "reminders": "10m 1h",
                "is_active": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.reminders, "1h 10m")
        self.assertIn('type="date"', str(form["starts_at"]))
        self.assertIn('type="time"', str(form["ends_at"]))
        form = SiteNoticeForm({"reminders": "nope"})
        self.assertFalse(form.is_valid())
        self.assertIn("reminders", form.errors)
